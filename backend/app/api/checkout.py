"""
Checkout API — Creates Razorpay orders for embedded Checkout flow.
Returns only public data (key_id, order_id) — secret never exposed.
Frontend opens Razorpay Checkout widget, payment.captured webhook handles the rest.
"""
import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.config import settings
from app.services.razorpay_client import razorpay_client
from app.models.customer import CustomerContext

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/checkout", tags=["checkout"])


class CheckoutOrderRequest(BaseModel):
    amount: int = Field(..., ge=100, description="Amount in paise (min ₹1)")
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    customer_id: str = Field(..., min_length=1, max_length=128)
    receipt: str | None = None


@router.post("/order")
def create_checkout_order(payload: CheckoutOrderRequest, db: Session = Depends(get_db)):
    """
    Create a Razorpay order for embedded Checkout.
    Returns {order_id, key_id, amount, currency, customer_id} — safe for frontend.
    """
    # Validate customer exists
    customer = db.query(CustomerContext).filter(CustomerContext.id == payload.customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail=f"Customer {payload.customer_id} not found")

    receipt = payload.receipt or f"co_{uuid.uuid4().hex[:12]}"
    notes = {"customer_id": payload.customer_id, "merchant_id": settings.MERCHANT_ID, "source": "checkout"}

    try:
        razorpay_order = razorpay_client.create_order(
            amount=payload.amount,
            currency=payload.currency,
            receipt=receipt,
            notes=notes,
        )
        order_id = razorpay_order.get("id")
        if not order_id:
            raise HTTPException(status_code=502, detail="Razorpay returned no order_id")

        logger.info("Checkout order created: %s for customer %s", order_id, payload.customer_id)
        return {
            "order_id": order_id,
            "key_id": settings.RAZORPAY_KEY_ID,  # public key — safe for frontend
            "amount": payload.amount,
            "currency": payload.currency,
            "customer_id": payload.customer_id,
            "receipt": receipt,
        }
    except TimeoutError as e:
        logger.warning("Checkout order creation timed out: %s", e)
        raise HTTPException(status_code=503, detail="Razorpay unavailable — try again")
    except Exception as e:
        logger.exception("Checkout order creation failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Razorpay error: {str(e)}")
