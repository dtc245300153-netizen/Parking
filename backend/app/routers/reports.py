from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ParkingTicket, Vehicle
from ..security import require_admin
from ..time_utils import to_vietnam_datetime

router = APIRouter(prefix="/api/reports", tags=["Reports"])


@router.get("/revenue")
def revenue_report(
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):
    tickets = db.query(
        ParkingTicket.check_out,
        ParkingTicket.amount,
    ).filter(
        func.upper(ParkingTicket.status).in_(("PAID", "COMPLETED", "FINISHED")),
        ParkingTicket.check_out.isnot(None),
    ).all()

    daily_totals = {}
    for check_out, amount in tickets:
        local_date = to_vietnam_datetime(check_out).date().isoformat()
        daily_totals[local_date] = daily_totals.get(local_date, 0) + float(amount or 0)

    return [
        {"date": date, "total_revenue": daily_totals[date]}
        for date in sorted(daily_totals)
    ]


@router.get("/vehicles")
def vehicle_report(
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):
    result = db.query(
        Vehicle.vehicle_type,
        func.count(Vehicle.id).label("count"),
    ).group_by(Vehicle.vehicle_type).all()

    return [{"vehicle_type": row.vehicle_type, "count": row.count} for row in result]
