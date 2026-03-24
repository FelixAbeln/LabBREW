import { useState } from 'react'
import { makeEmptyActionForm } from './ruleUtils'

export function useRuleForm() {
  const [ruleForm, setRuleForm] = useState(null)

  function updateRuleForm(patch) {
    setRuleForm((current) => (current ? { ...current, ...patch } : current))
  }

  function updateRuleParam(name, value) {
    setRuleForm((current) => {
      if (!current) return current
      return {
        ...current,
        operatorParams: {
          ...current.operatorParams,
          [name]: value,
        },
      }
    })
  }

  function addRuleAction() {
    setRuleForm((current) => {
      if (!current) return current
      return {
        ...current,
        actions: [...(current.actions || []), makeEmptyActionForm()],
      }
    })
  }

  function removeRuleAction(actionId) {
    setRuleForm((current) => {
      if (!current) return current
      const nextActions = (current.actions || []).filter((action) => action.id !== actionId)
      return {
        ...current,
        actions: nextActions.length ? nextActions : [makeEmptyActionForm()],
      }
    })
  }

  function updateRuleAction(actionId, patch) {
    setRuleForm((current) => {
      if (!current) return current
      return {
        ...current,
        actions: (current.actions || []).map((action) =>
          action.id === actionId ? { ...action, ...patch } : action,
        ),
      }
    })
  }

  return { ruleForm, setRuleForm, updateRuleForm, updateRuleParam, addRuleAction, removeRuleAction, updateRuleAction }
}
