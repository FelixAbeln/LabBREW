export function getRunToggle(state) {
  if (state === 'paused') {
    return {
      label: 'Resume',
      path: '/schedule/resume',
      className: 'toggle-button is-resume is-paused',
      disabled: false,
      hint: 'Schedule is paused',
    }
  }

  if (state === 'running') {
    return {
      label: 'Pause',
      path: '/schedule/pause',
      className: 'toggle-button is-pause',
      disabled: false,
      hint: 'Schedule is running',
    }
  }

  return {
    label: 'Pause',
    path: null,
    className: 'toggle-button',
    disabled: true,
    hint: 'Schedule not running',
  }
}
