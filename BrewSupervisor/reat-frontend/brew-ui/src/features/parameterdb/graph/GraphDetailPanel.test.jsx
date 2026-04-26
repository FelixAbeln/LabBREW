import { strict as assert } from 'node:assert';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, it } from 'vitest';
import { GraphDetailPanel } from './GraphDetailPanel.jsx';

function render(selected) {
  return renderToStaticMarkup(
    GraphDetailPanel({
      selected,
      graph: { dependencies: {}, write_targets: {}, warnings: [] },
      onClear: () => {},
    }),
  );
}

describe('GraphDetailPanel signal rendering', () => {
  it('renders raw signal when selected.signal_value is provided', () => {
    const html = render({
      name: 'temp',
      paramType: 'static',
      value: 12,
      signal_value: 10,
      scanIndex: 1,
      config: {},
      state: {},
      metadata: {},
    });

    assert.ok(html.includes('Signal (raw)'));
    assert.ok(html.includes('10'));
  });

  it('renders raw signal when selected.signalValue is provided', () => {
    const html = render({
      name: 'temp',
      paramType: 'static',
      value: 12,
      signalValue: 11,
      scanIndex: 1,
      config: {},
      state: {},
      metadata: {},
    });

    assert.ok(html.includes('Signal (raw)'));
    assert.ok(html.includes('11'));
  });

  it('does not render raw signal row when signal is missing', () => {
    const html = render({
      name: 'temp',
      paramType: 'static',
      value: 12,
      scanIndex: 1,
      config: {},
      state: {},
      metadata: {},
    });

    assert.equal(html.includes('Signal (raw)'), false);
  });
});
