export function getRunToggle(state) {
  if (state === 'paused') {
    return {
      label: 'Resume',
      path: '/scenario/run/resume',
      className: 'toggle-button is-resume is-paused',
      disabled: false,
      hint: 'Scenario run is paused',
    }
  }

  if (state === 'running') {
    return {
      label: 'Pause',
      path: '/scenario/run/pause',
      className: 'toggle-button is-pause',
      disabled: false,
      hint: 'Scenario run is active',
    }
  }

  return {
    label: 'Pause',
    path: null,
    className: 'toggle-button',
    disabled: true,
    hint: 'No active scenario run',
  }
}
