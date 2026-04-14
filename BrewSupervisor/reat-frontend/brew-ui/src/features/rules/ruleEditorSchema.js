function makeField(key, label, options = {}) {
  return {
    kind: 'field',
    field: {
      key,
      label,
      ...options,
    },
  }
}

export function buildRuleEditorApp({ selectedOperator, operators }) {
  const operatorOptions = Array.isArray(operators)
    ? operators.map((operator) => ({
        value: operator.name,
        label: operator.label || operator.name,
      }))
    : []

  const operatorParamItems = Object.entries(selectedOperator?.param_schema || {}).map(([key, schema]) => {
    const type = schema?.type === 'number' ? 'float' : 'string'
    return makeField(`operatorParams.${key}`, key, {
      type,
      required: Boolean(schema?.required),
      placeholder: schema?.required ? 'required' : 'optional',
      step: type === 'float' ? 'any' : undefined,
    })
  })

  if (!operatorParamItems.length) {
    operatorParamItems.push({
      kind: 'notice',
      text: 'This operator has no extra parameters.',
    })
  }

  return {
    kind: 'sections',
    version: 1,
    sections: [
      {
        id: 'rule-main',
        title: 'Rule',
        items: [
          makeField('id', 'Rule id', {
            type: 'string',
            placeholder: 'manual-pressure-override',
          }),
          makeField('enabled', 'Enabled', {
            type: 'bool',
          }),
          makeField('source', 'Parameter', {
            type: 'string',
            placeholder: 'set_temp_Fermentor',
            list: 'rule-target-options',
          }),
          makeField('operator', 'Operator', {
            type: 'enum',
            options: operatorOptions,
          }),
          ...(selectedOperator?.supports_for_s
            ? [
                makeField('for_s', 'For seconds', {
                  type: 'float',
                  step: '0.1',
                  placeholder: 'optional',
                }),
              ]
            : []),
        ],
      },
      {
        id: 'rule-params',
        title: 'Operator Parameters',
        items: operatorParamItems,
      },
      {
        id: 'rule-actions',
        title: 'Actions',
        items: [
          {
            kind: 'action_list',
            add_label: 'Add action',
          },
        ],
      },
      {
        id: 'rule-behavior',
        title: 'Behavior',
        items: [
          makeField('releaseWhenClear', 'Release when clear', {
            type: 'bool',
          }),
        ],
      },
    ],
  }
}

export default buildRuleEditorApp
