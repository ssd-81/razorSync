import time
import logging
import hmac
import hashlib
from typing import Optional, Dict, Any

import httpx
from app.config import settings

logger = logging.getLogger(__name__)


class RazorpayClient:
    """
    Thin wrapper around Razorpay Test Mode API.
    Handles timeout (5s), retry with backoff, graceful fallback,
    and SIMULATE_RAZORPAY_FAILURE toggle that triggers same path as real timeout.
    """

    TIMEOUT_SECONDS = 5.0
    MAX_RETRIES = 2
    BASE_URL = "https://api.razorpay.com/v1"

    def __init__(self):
        self.key_id = settings.RAZORPAY_KEY_ID
        self.key_secret = settings.RAZORPAY_KEY_SECRET
        # In-memory override for failure drills (can be flipped via /api/v1/ops/failure-toggle)
        self._force_failure = settings.SIMULATE_RAZORPAY_FAILURE

    def set_failure_mode(self, enabled: bool):
        self._force_failure = enabled
        logger.info("Razorpay failure simulation set to %s", enabled)

    @property
    def failure_mode(self) -> bool:
        return self._force_failure

    def _check_failure_flag(self):
        if self._force_failure:
            raise TimeoutError("Simulated RazorPay failure (SIMULATE_RAZORPAY_FAILURE=True)")

    def _auth(self):
        return (self.key_id, self.key_secret)

    def create_order(self, amount: int, currency: str = "INR", receipt: Optional[str] = None, notes: Optional[dict] = None) -> Dict[str, Any]:
        """
        Create order in Razorpay test mode. Returns Razorpay order dict.
        On failure (timeout or API error) raises or returns fallback marker.
        """
        self._check_failure_flag()

        payload = {
            "amount": amount,
            "currency": currency,
            "receipt": receipt or f"rcpt_{int(time.time())}",
        }
        if notes:
            payload["notes"] = notes

        last_exc = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                # Prefer razorpay SDK if available
                try:
                    import razorpay

                    client = razorpay.Client(auth=(self.key_id, self.key_secret))
                    # razorpay SDK handles its own HTTP; we wrap with timeout via httpx fallback if SDK lacks timeout
                    order = client.order.create(payload)
                    logger.info("Razorpay order created via SDK: %s", order.get("id"))
                    return order
                except TimeoutError:
                    raise
                except Exception as e:
                    # SDK failed, try httpx with explicit timeout
                    logger.warning("Razorpay SDK failed (attempt %s): %s, trying httpx", attempt, e)
                    with httpx.Client(timeout=self.TIMEOUT_SECONDS, auth=self._auth()) as http:
                        resp = http.post(f"{self.BASE_URL}/orders", json=payload)
                        resp.raise_for_status()
                        order = resp.json()
                        logger.info("Razorpay order created via httpx: %s", order.get("id"))
                        return order

            except TimeoutError as e:
                last_exc = e
                logger.warning("Razorpay timeout (attempt %s): %s", attempt, e)
                if attempt < self.MAX_RETRIES:
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                raise
            except httpx.TimeoutException as e:
                last_exc = e
                logger.warning("Razorpay httpx timeout (attempt %s): %s", attempt, e)
                if attempt < self.MAX_RETRIES:
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                raise TimeoutError(str(e)) from e
            except Exception as e:
                # Graceful fallback for rate-limit (429) — treat same as timeout, not 502
                msg = str(e)
                if "429" in msg or "Too Many Requests" in msg:
                    logger.warning("Razorpay rate-limited 429 (attempt %s): %s — will fallback", attempt, e)
                    # Backoff then raise as TimeoutError to trigger fallback path in orders.py
                    if attempt < self.MAX_RETRIES:
                        time.sleep(1.0 * (2 ** attempt))
                        continue
                    raise TimeoutError(f"Razorpay rate-limited (429) — using fallback: {e}") from e
                last_exc = e
                logger.warning("Razorpay API error (attempt %s): %s", attempt, e)
                if attempt < self.MAX_RETRIES:
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                raise

        raise last_exc or RuntimeError("Razorpay order creation failed")

    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        """
        Verify Razorpay webhook signature (HMAC SHA256).
        """
        secret = settings.RAZORPAY_WEBHOOK_SECRET
        if not secret:
            logger.warning("RAZORPAY_WEBHOOK_SECRET not set — skipping verification (dev mode)")
            return True
        if not signature:
            return False
        try:
            import razorpay

            client = razorpay.Client(auth=(self.key_id, self.key_secret))
            client.utility.verify_webhook_signature(payload.decode("utf-8"), signature, secret)
            return True
        except Exception as e:
            # manual fallback
            expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
            if hmac.compare_digest(expected, signature):
                return True
            logger.warning("Webhook signature verification failed: %s", e)
            return False


# Singleton for app-wide use
razorpay_client = RazorpayClient()
