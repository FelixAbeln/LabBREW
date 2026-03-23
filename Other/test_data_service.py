"""
Example and test client for the Data Service.

This demonstrates:
1. Setting up a measurement session
2. Starting/stopping measurements
3. Recording loadsteps
4. Retrieving status

Usage:
    python Other/test_data_service.py
    
Requires:
    - Data Service running on http://localhost:8700
    - ParameterDB running and populated with test parameters
"""

import requests
import time
import json
from typing import Dict, Any


CONTROL_BASE_URL = "http://127.0.0.1:8767"


class DataServiceClient:
    """Simple client for the Data Service API."""

    def __init__(self, base_url: str = "http://localhost:8700"):
        """Initialize the client.
        
        Args:
            base_url: Base URL of the Data Service
        """
        self.base_url = base_url

    def health(self) -> Dict[str, Any]:
        """Check service health."""
        resp = requests.get(f"{self.base_url}/health")
        resp.raise_for_status()
        return resp.json()

    def status(self) -> Dict[str, Any]:
        """Get service status."""
        resp = requests.get(f"{self.base_url}/status")
        resp.raise_for_status()
        return resp.json()

    def setup_measurement(self, parameters: list, hz: float = 10.0,
                         output_format: str = "parquet",
                         session_name: str = "") -> Dict[str, Any]:
        """Setup a measurement session."""
        payload = {
            "parameters": parameters,
            "hz": hz,
            "output_dir": "data/measurements",
            "output_format": output_format,
            "session_name": session_name
        }
        resp = requests.post(f"{self.base_url}/measurement/setup", json=payload)
        resp.raise_for_status()
        return resp.json()

    def measure_start(self) -> Dict[str, Any]:
        """Start recording."""
        resp = requests.post(f"{self.base_url}/measurement/start")
        resp.raise_for_status()
        return resp.json()

    def measure_stop(self) -> Dict[str, Any]:
        """Stop recording."""
        resp = requests.post(f"{self.base_url}/measurement/stop")
        resp.raise_for_status()
        return resp.json()

    def take_loadstep(self, duration_seconds: float = 30.0,
                     loadstep_name: str = "",
                     parameters: list = None) -> Dict[str, Any]:
        """Record a loadstep."""
        payload = {
            "duration_seconds": duration_seconds,
            "loadstep_name": loadstep_name,
            "parameters": parameters
        }
        resp = requests.post(f"{self.base_url}/loadstep/take", json=payload)
        resp.raise_for_status()
        return resp.json()


def build_parameters_from_control_snapshot(
    control_base_url: str = CONTROL_BASE_URL,
    count: int = 2,
) -> list[str]:
    """Build a measurement parameter list from the control service snapshot."""
    resp = requests.get(f"{control_base_url}/system/snapshot")
    resp.raise_for_status()

    payload = resp.json()
    values = payload.get("values", {}) if isinstance(payload, dict) else {}
    if not isinstance(values, dict):
        return []

    preferred: list[str] = []
    fallback: list[str] = []

    for name, value in values.items():
        if not isinstance(name, str) or not name:
            continue
        fallback.append(name)
        if value is not None:
            preferred.append(name)

    selected = preferred[:count] if preferred else fallback[:count]
    return selected


def print_http_error(error: requests.exceptions.HTTPError) -> None:
    print(f"✗ HTTP error: {error}")
    response = error.response
    if response is None:
        return
    try:
        print(json.dumps(response.json(), indent=2))
    except ValueError:
        if response.text:
            print(response.text)


def example_basic_recording():
    """Example: Basic recording session."""
    print("\n" + "="*60)
    print("Example 1: Basic Recording Session")
    print("="*60)

    client = DataServiceClient()

    try:
        # Check health
        health = client.health()
        print(f"✓ Service health: {health['status']}")

        print("\n1. Building setup from control snapshot...")
        parameters = build_parameters_from_control_snapshot(count=2)
        if not parameters:
            print("✗ No parameters found in control service snapshot")
            print(f"   Check control service at {CONTROL_BASE_URL}/system/snapshot")
            return
        print(f"✓ Using parameters from control snapshot: {parameters}")

        # Setup measurement
        print("\n2. Setting up measurement...")
        setup_result = client.setup_measurement(
            parameters=parameters,
            hz=10.0,
            output_format="parquet",
            session_name="example_001"
        )

        print(f"✓ Setup complete: {json.dumps(setup_result, indent=2)}")

        # Start recording
        print("\n3. Starting measurement...")
        start_result = client.measure_start()
        print(f"✓ {start_result['message']}")

        # Let it record for a bit
        print("\n4. Recording for 5 seconds...")
        time.sleep(5)

        # Check status
        status = client.status()
        print(f"✓ Status: {json.dumps(status, indent=2)}")

        # Stop recording
        print("\n5. Stopping measurement...")
        stop_result = client.measure_stop()
        print(f"✓ {json.dumps(stop_result, indent=2)}")

    except requests.exceptions.ConnectionError:
        print("✗ Cannot connect to Data Service")
        print(f"   Make sure it's running on {client.base_url}")
        print("   Start with: python run_service_data.py")
    except requests.exceptions.HTTPError as e:
        print_http_error(e)
    except Exception as e:
        print(f"✗ Error: {e}")


def example_with_loadsteps():
    """Example: Recording with multiple loadsteps."""
    print("\n" + "="*60)
    print("Example 2: Recording with Loadsteps")
    print("="*60)

    client = DataServiceClient()

    try:
        print("1. Building setup from control snapshot...")
        parameters = build_parameters_from_control_snapshot(count=2)
        if not parameters:
            print("✗ No parameters found in control service snapshot")
            return
        print(f"✓ Using parameters from control snapshot: {parameters}")

        # Setup
        print("\n2. Setting up measurement...")
        client.setup_measurement(
            parameters=parameters,
            hz=20.0,
            output_format="csv",  # Use CSV for easier inspection
            session_name="example_loadsteps"
        )

        print("✓ Setup complete")

        # Start recording
        print("\n3. Starting measurement...")
        client.measure_start()
        print("✓ Recording started")

        # Record first loadstep
        print("\n4. Recording loadstep 1 (10s)...")
        client.take_loadstep(
            duration_seconds=10.0,
            loadstep_name="phase_1",
            parameters=None  # Use default parameters
        )
        print("✓ Loadstep 1 started")
        time.sleep(5)

        # Check status
        status = client.status()
        print(f"   Active loadsteps: {status['active_loadsteps']}")
        print(f"   Samples recorded: {status['samples_recorded']}")

        # Wait for first loadstep to complete
        print("\n5. Waiting for loadstep 1 to complete...")
        time.sleep(10)

        # Record second loadstep
        print("\n6. Recording loadstep 2 (10s)...")
        client.take_loadstep(
            duration_seconds=10.0,
            loadstep_name="phase_2"
        )
        print("✓ Loadstep 2 started")

        # Wait for completion
        time.sleep(12)

        # Stop and get results
        print("\n7. Stopping measurement...")
        stop_result = client.measure_stop()
        print(f"✓ Recording stopped")
        print(f"  - Total samples: {stop_result['samples_recorded']}")
        print(f"  - Output file: {stop_result['file']}")
        print(f"  - Completed loadsteps: {stop_result['completed_loadsteps_count']}")

        # Print loadstep results
        if stop_result.get('loadsteps'):
            print("\n  Loadstep Results:")
            for ls in stop_result['loadsteps']:
                print(f"    {ls['name']}:")
                print(f"      Duration: {ls['duration_seconds']}s")
                print(f"      Averages:")
                for param, value in ls['average'].items():
                    print(f"        {param}: {value}")

    except requests.exceptions.ConnectionError:
        print("✗ Cannot connect to Data Service")
    except requests.exceptions.HTTPError as e:
        print_http_error(e)
    except Exception as e:
        print(f"✗ Error: {e}")


def example_high_frequency():
    """Example: High-frequency recording."""
    print("\n" + "="*60)
    print("Example 3: High-Frequency Recording (100 Hz)")
    print("="*60)

    client = DataServiceClient()

    try:
        print("1. Building setup from control snapshot...")
        parameters = build_parameters_from_control_snapshot(count=1)
        if not parameters:
            print("✗ No parameters found in control service snapshot")
            return
        print(f"✓ Using parameter from control snapshot: {parameters}")

        # Setup at high frequency
        print("\n2. Setting up high-frequency measurement (100 Hz)...")
        client.setup_measurement(
            parameters=parameters,
            hz=100.0,  # 100 samples per second
            output_format="parquet",
            session_name="example_hf"
        )

        print("✓ Setup complete")

        # Start recording
        print("\n3. Starting measurement...")
        client.measure_start()
        print("✓ Recording started")

        # Record for 3 seconds
        print("\n4. Recording at 100 Hz for 3 seconds...")
        time.sleep(3)

        # Stop
        stop_result = client.measure_stop()
        samples = stop_result['samples_recorded']
        duration = 3.0
        actual_hz = samples / duration if duration > 0 else 0

        print(f"✓ Recording stopped")
        print(f"  - Total samples: {samples}")
        print(f"  - Duration: {duration}s")
        print(f"  - Actual Hz: {actual_hz:.1f}")

    except requests.exceptions.HTTPError as e:
        print_http_error(e)
    except Exception as e:
        print(f"✗ Error: {e}")


def example_different_formats():
    """Example: Testing different output formats."""
    print("\n" + "="*60)
    print("Example 4: Different Output Formats")
    print("="*60)

    client = DataServiceClient()
    formats = ["parquet", "csv", "jsonl"]

    try:
        print("Building setup from control snapshot...")
        parameters = build_parameters_from_control_snapshot(count=1)
        if not parameters:
            print("✗ No parameters found in control service snapshot")
            return
        print(f"✓ Using parameter from control snapshot: {parameters}")

        # Test each format
        for fmt in formats:
            try:
                print(f"\n1. Testing {fmt.upper()} format...")

                # Setup
                client.setup_measurement(
                    parameters=parameters,
                    hz=5.0,
                    output_format=fmt,
                    session_name=f"example_{fmt}"
                )

                # Record
                client.measure_start()
                time.sleep(2)
                stop_result = client.measure_stop()

                print(f"✓ {fmt.upper()} file: {stop_result['file']}")
                print(f"  Samples: {stop_result['samples_recorded']}")

            except Exception as e:
                print(f"✗ Error with {fmt}: {e}")

    except requests.exceptions.ConnectionError:
        print("✗ Cannot connect to Data Service")
    except requests.exceptions.HTTPError as e:
        print_http_error(e)
    except Exception as e:
        print(f"✗ Error: {e}")


if __name__ == "__main__":
    print("Data Service Examples & Tests")
    print("==============================")

    # Run examples
    try:
        example_basic_recording()
        # example_with_loadsteps()
        # example_high_frequency()
        # example_different_formats()

        print("\n" + "="*60)
        print("Examples completed!")
        print("="*60)

    except ConnectionError:
        print("\n✗ Cannot connect to Data Service")
        print("Make sure the service is running on http://localhost:8700")
        print("You can start it with: python run_service_data.py")
