from fastapi import APIRouter, HTTPException

from ..rules.storage import delete_rule, load_rules, save_rule

router = APIRouter(prefix="/rules")


@router.get("/")
def list_rules():
    return load_rules()


@router.post("/")
def create_rule(rule: dict):
    try:
        save_rule(rule)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "id": rule["id"]}


@router.delete("/{rule_id}")
def remove_rule(rule_id: str):
    deleted = delete_rule(rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")
    return {"ok": True, "id": rule_id}
