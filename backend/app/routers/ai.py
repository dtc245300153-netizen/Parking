from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Customer, User
from ..schemas.parking import AIChatRequest
from ..security import canonical_role, get_current_user
from ..services.ai import contains_revenue_question
from ..services.ai_service import build_ai_context, generate_answer_from_context, save_ai_conversation

router = APIRouter(prefix="/api/ai", tags=["AI"])


def _customer_context_id(db: Session, current_user: User) -> int | None:
    if canonical_role(current_user.role) == "ADMIN":
        return None
    customer = (
        db.query(Customer)
        .filter(Customer.user_id == current_user.id)
        .first()
    )
    return customer.id if customer else 0


@router.post("/chat")
def chat_with_ai(
    payload: AIChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if canonical_role(current_user.role) not in {"CUSTOMER", "ADMIN"}:
        raise HTTPException(status_code=403, detail="Chỉ khách hàng mới được hỏi AI")
    if not payload.question or not payload.question.strip():
        raise HTTPException(status_code=400, detail="Câu hỏi không được để trống")
    if (
        canonical_role(current_user.role) != "ADMIN"
        and contains_revenue_question(payload.question)
    ):
        raise HTTPException(status_code=403, detail="Bạn không có quyền xem doanh thu")

    context = build_ai_context(db, _customer_context_id(db, current_user))
    answer = generate_answer_from_context(payload.question, context)
    save_ai_conversation(db, current_user.id, payload.question, answer)
    return {"answer": answer, "source": "database", "confidence": "high"}


@router.post("/analyze")
def analyze_parking(
    payload: AIChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if canonical_role(current_user.role) not in {"CUSTOMER", "ADMIN"}:
        raise HTTPException(status_code=403, detail="Chỉ khách hàng mới được hỏi AI")
    if (
        canonical_role(current_user.role) != "ADMIN"
        and contains_revenue_question(payload.question or "")
    ):
        raise HTTPException(status_code=403, detail="Bạn không có quyền xem doanh thu")
    context = build_ai_context(db, _customer_context_id(db, current_user))
    question = payload.question or "Phân tích tình trạng bãi đỗ hiện tại"
    answer = generate_answer_from_context(question, context)
    return {"answer": answer, "source": "database", "analysis": context.get("summary", {})}


@router.get("/history")
def get_ai_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if canonical_role(current_user.role) not in {"CUSTOMER", "ADMIN"}:
        raise HTTPException(status_code=403, detail="Chỉ khách hàng mới được xem lịch sử hỏi AI")
    from ..models import AIConversation

    rows = db.query(AIConversation).filter(AIConversation.user_id == current_user.id).order_by(AIConversation.id.desc()).all()
    return [{"id": row.id, "question": row.question, "answer": row.answer, "created_at": row.created_at.isoformat()} for row in rows]
