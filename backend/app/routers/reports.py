from datetime import datetime
from io import BytesIO

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session
import xlsxwriter

from ..database import get_db
from ..models import Employee, ParkingTicket, Vehicle
from ..security import require_admin
from ..time_utils import to_vietnam_datetime

router = APIRouter(prefix="/api/reports", tags=["Reports"])


@router.get("/revenue.xlsx")
def export_revenue_excel(
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):
    del current_user
    tickets = (
        db.query(ParkingTicket)
        .filter(
            func.upper(ParkingTicket.status).in_(("PAID", "COMPLETED", "FINISHED")),
            ParkingTicket.check_out.isnot(None),
        )
        .order_by(ParkingTicket.check_out, ParkingTicket.id)
        .all()
    )

    daily_totals: dict[str, float] = {}
    ticket_rows = []
    for ticket in tickets:
        exited_at = to_vietnam_datetime(ticket.check_out)
        day = exited_at.date().isoformat()
        amount = float(ticket.amount or 0)
        daily_totals[day] = daily_totals.get(day, 0) + amount
        employee = (
            db.query(Employee)
            .filter(Employee.id == ticket.employee_id)
            .first()
        )
        ticket_rows.append(
            (
                ticket.ticket_code,
                ticket.vehicle.license_plate if ticket.vehicle else "",
                ticket.vehicle.vehicle_type if ticket.vehicle else "",
                to_vietnam_datetime(ticket.check_in).replace(tzinfo=None)
                if ticket.check_in
                else None,
                exited_at.replace(tzinfo=None),
                amount,
                employee.user.full_name
                if employee and employee.user
                else "",
            )
        )

    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    summary = workbook.add_worksheet("Tổng quan")
    details = workbook.add_worksheet("Chi tiết vé")
    title_format = workbook.add_format(
        {"bold": True, "font_size": 16, "font_color": "#FFFFFF", "bg_color": "#1748A0"}
    )
    header_format = workbook.add_format(
        {"bold": True, "font_color": "#FFFFFF", "bg_color": "#2563EB", "border": 1}
    )
    money_format = workbook.add_format({"num_format": '#,##0 "₫"'})
    date_format = workbook.add_format({"num_format": "dd/mm/yyyy hh:mm"})
    summary.merge_range("A1:B1", "BÁO CÁO DOANH THU BÃI ĐỖ XE", title_format)
    summary.write("A3", "Ngày xuất")
    summary.write_datetime("B3", datetime.now(), date_format)
    summary.write("A4", "Tổng doanh thu")
    summary.write_number("B4", sum(daily_totals.values()), money_format)
    summary.write("A5", "Số vé đã thanh toán")
    summary.write_number("B5", len(ticket_rows))

    summary.write_row(6, 0, ("Ngày", "Số vé", "Doanh thu"), header_format)
    counts_by_day: dict[str, int] = {}
    for row in ticket_rows:
        day = row[4].date().isoformat()
        counts_by_day[day] = counts_by_day.get(day, 0) + 1
    for row_number, day in enumerate(sorted(daily_totals), start=7):
        summary.write(row_number, 0, day)
        summary.write_number(row_number, 1, counts_by_day[day])
        summary.write_number(row_number, 2, daily_totals[day], money_format)
    summary.set_column("A:A", 24)
    summary.set_column("B:B", 20)
    summary.set_column("C:C", 20)
    summary.freeze_panes(7, 0)

    detail_headers = (
        "Mã vé",
        "Biển số",
        "Loại xe",
        "Thời gian vào",
        "Thời gian ra",
        "Phí",
        "Nhân viên thu",
    )
    details.write_row(0, 0, detail_headers, header_format)
    for row_number, row in enumerate(ticket_rows, start=1):
        for column, value in enumerate(row):
            if isinstance(value, datetime):
                details.write_datetime(row_number, column, value, date_format)
            elif isinstance(value, (int, float)):
                details.write_number(row_number, column, value, money_format)
            else:
                details.write_string(row_number, column, value)
    details.set_column("A:A", 22)
    details.set_column("B:C", 16)
    details.set_column("D:E", 20)
    details.set_column("F:F", 18)
    details.set_column("G:G", 24)
    details.freeze_panes(1, 0)
    details.autofilter(0, 0, max(1, len(ticket_rows)), len(detail_headers) - 1)
    workbook.close()

    filename = f"bao-cao-doanh-thu-{datetime.now():%Y%m%d-%H%M%S}.xlsx"
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
