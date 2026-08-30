from backend.app.schemas.payment import PaymentStatus

ALLOWED_TRANSITIONS = {
    PaymentStatus.CREATED: {
        PaymentStatus.PENDING,
        PaymentStatus.FAILED,
    },

    PaymentStatus.PENDING: {
        PaymentStatus.AUTHORIZED,
        PaymentStatus.CAPTURED,
        PaymentStatus.FAILED,
        PaymentStatus.UNKNOWN,
    },

    PaymentStatus.AUTHORIZED: {
        PaymentStatus.CAPTURED,
        PaymentStatus.UNKNOWN,
    },

    PaymentStatus.UNKNOWN: {
        PaymentStatus.PENDING,
        PaymentStatus.AUTHORIZED,
        PaymentStatus.CAPTURED,
        PaymentStatus.FAILED,
    },

    PaymentStatus.CAPTURED: set(),

    PaymentStatus.FAILED: set(),

}

def can_transition(
        current_status: PaymentStatus,
        new_status: PaymentStatus
) -> bool:
    allowed_next_states = ALLOWED_TRANSITIONS.get(
        current_status,
        set()
    )

    return new_status in allowed_next_states

def transition_payment_status(
        current_status: PaymentStatus,
        new_status: PaymentStatus,
):
    if not can_transition(
        current_status,
        new_status
    ):
        return {
            "success": False,
            "current_status": current_status,
            "requested_status": new_status,
            "reason_code": "INVALID_PAYMENT_STATE_TRANSITION",
            "message": (
                f"Payment cannot transition from "
                f"{current_status.value} to "
                f"{new_status.value}."
            )
        }

    return {
        "success": True,
        "previous_status": current_status,
        "new_status": new_status,
        "reason_code": "PAYMENT_STATE_TRANSITION_ALLOWED",
        "message": (
            f"payment can transition from "
            f"{current_status.value} to "
            f"{new_status.value}."
        )
    }
