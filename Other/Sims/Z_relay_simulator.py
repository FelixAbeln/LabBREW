from __future__ import annotations

import argparse
import socket
import struct
import threading
from typing import List, Tuple


class RelaySimulator:
    def __init__(self, host: str = '127.0.0.1', port: int = 502, unit_id: int = 1, channel_count: int = 8):
        self.host = host
        self.port = int(port)
        self.unit_id = int(unit_id)
        self.channel_count = int(channel_count)
        self._states: List[bool] = [False] * self.channel_count
        self._lock = threading.RLock()
        self._server_socket: socket.socket | None = None
        self._stop_event = threading.Event()
        self._client_threads: List[threading.Thread] = []

    def serve_forever(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.host, self.port))
            server.listen(20)
            server.settimeout(0.5)
            self._server_socket = server
            print(f'Relay simulator listening on {self.host}:{self.port} (unit_id={self.unit_id}, channels={self.channel_count})')
            print('Commands: status | on <n> | off <n> | toggle <n> | all on | all off | quit')

            console_thread = threading.Thread(target=self._console_loop, daemon=True)
            console_thread.start()

            while not self._stop_event.is_set():
                try:
                    conn, addr = server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                thread = threading.Thread(target=self._handle_client, args=(conn, addr), daemon=True)
                thread.start()
                self._client_threads.append(thread)

    def shutdown(self) -> None:
        self._stop_event.set()
        if self._server_socket is not None:
            try:
                self._server_socket.close()
            except OSError:
                pass

    def _console_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                command = input('sim> ').strip()
            except EOFError:
                self.shutdown()
                return
            except KeyboardInterrupt:
                self.shutdown()
                return

            if not command:
                continue
            lower = command.lower()

            if lower in {'quit', 'exit'}:
                self.shutdown()
                return
            if lower == 'status':
                self._print_states()
                continue
            if lower in {'all on', 'allon'}:
                with self._lock:
                    self._states = [True] * self.channel_count
                self._print_states()
                continue
            if lower in {'all off', 'alloff'}:
                with self._lock:
                    self._states = [False] * self.channel_count
                self._print_states()
                continue

            parts = lower.split()
            if len(parts) == 2 and parts[0] in {'on', 'off', 'toggle'}:
                try:
                    channel = int(parts[1])
                except ValueError:
                    print('Invalid channel number.')
                    continue
                if not 1 <= channel <= self.channel_count:
                    print(f'Channel must be 1..{self.channel_count}.')
                    continue
                with self._lock:
                    index = channel - 1
                    if parts[0] == 'on':
                        self._states[index] = True
                    elif parts[0] == 'off':
                        self._states[index] = False
                    else:
                        self._states[index] = not self._states[index]
                self._print_states()
                continue

            print('Unknown command.')

    def _print_states(self) -> None:
        with self._lock:
            rendered = ' '.join(f'{i + 1}:{"ON" if state else "off"}' for i, state in enumerate(self._states))
        print(rendered)

    def _handle_client(self, conn: socket.socket, addr: Tuple[str, int]) -> None:
        print(f'Client connected: {addr[0]}:{addr[1]}')
        with conn:
            conn.settimeout(2.0)
            while not self._stop_event.is_set():
                try:
                    header = self._recv_exact(conn, 7)
                except (OSError, TimeoutError, ConnectionError):
                    break
                if not header:
                    break

                tx_id, protocol_id, length, unit_id = struct.unpack('>HHHB', header)
                if protocol_id != 0:
                    break
                try:
                    pdu = self._recv_exact(conn, length - 1)
                except (OSError, TimeoutError, ConnectionError):
                    break
                if not pdu:
                    break

                function_code = pdu[0]
                payload = pdu[1:]
                if unit_id != self.unit_id:
                    response_pdu = bytes([function_code | 0x80, 0x0B])
                else:
                    response_pdu = self._process_request(function_code, payload)

                response = struct.pack('>HHHB', tx_id, 0, len(response_pdu) + 1, unit_id) + response_pdu
                try:
                    conn.sendall(response)
                except OSError:
                    break
        print(f'Client disconnected: {addr[0]}:{addr[1]}')

    @staticmethod
    def _recv_exact(conn: socket.socket, length: int) -> bytes:
        data = bytearray()
        while len(data) < length:
            chunk = conn.recv(length - len(data))
            if not chunk:
                raise ConnectionError('Socket closed')
            data.extend(chunk)
        return bytes(data)

    def _process_request(self, function_code: int, payload: bytes) -> bytes:
        try:
            if function_code == 0x01:
                return self._read_coils(payload)
            if function_code == 0x05:
                return self._write_single_coil(payload)
            if function_code == 0x0F:
                return self._write_multiple_coils(payload)
            return bytes([function_code | 0x80, 0x01])
        except ValueError:
            return bytes([function_code | 0x80, 0x02])

    def _read_coils(self, payload: bytes) -> bytes:
        if len(payload) != 4:
            raise ValueError('Bad payload')
        start_address, count = struct.unpack('>HH', payload)
        if count <= 0:
            raise ValueError('Bad count')
        with self._lock:
            if start_address + count > self.channel_count:
                raise ValueError('Address out of range')
            values = self._states[start_address:start_address + count]

        byte_count = (count + 7) // 8
        packed = bytearray(byte_count)
        for i, state in enumerate(values):
            if state:
                packed[i // 8] |= 1 << (i % 8)
        return bytes([0x01, byte_count]) + bytes(packed)

    def _write_single_coil(self, payload: bytes) -> bytes:
        if len(payload) != 4:
            raise ValueError('Bad payload')
        address, raw_value = struct.unpack('>HH', payload)
        if address >= self.channel_count:
            raise ValueError('Address out of range')
        if raw_value not in (0xFF00, 0x0000):
            raise ValueError('Bad value')
        value = raw_value == 0xFF00
        with self._lock:
            self._states[address] = value
        print(f'Relay {address + 1} -> {"ON" if value else "off"}')
        return bytes([0x05]) + payload

    def _write_multiple_coils(self, payload: bytes) -> bytes:
        if len(payload) < 5:
            raise ValueError('Bad payload')
        start_address, count, byte_count = struct.unpack('>HHB', payload[:5])
        packed = payload[5:]
        if len(packed) != byte_count:
            raise ValueError('Bad payload length')
        if start_address + count > self.channel_count:
            raise ValueError('Address out of range')

        values: List[bool] = []
        for i in range(count):
            bit = (packed[i // 8] >> (i % 8)) & 0x01
            values.append(bool(bit))

        with self._lock:
            for offset, value in enumerate(values):
                self._states[start_address + offset] = value
        self._print_states()
        return bytes([0x0F]) + struct.pack('>HH', start_address, count)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Fake Modbus TCP relay board for local testing.')
    parser.add_argument('--host', default='127.0.0.1', help='Listen host, default: 127.0.0.1')
    parser.add_argument('--port', type=int, default=502, help='Listen port, default: 502')
    parser.add_argument('--unit-id', type=int, default=1, help='Modbus unit/slave id, default: 1')
    parser.add_argument('--channels', type=int, default=8, help='Number of relay channels, default: 8')
    args = parser.parse_args()

    simulator = RelaySimulator(host=args.host, port=args.port, unit_id=args.unit_id, channel_count=args.channels)
    try:
        simulator.serve_forever()
    except KeyboardInterrupt:
        simulator.shutdown()
        print('\nSimulator stopped.')
