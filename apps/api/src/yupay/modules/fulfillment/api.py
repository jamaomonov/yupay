"""Public surface of the ``fulfillment`` module."""

from yupay.modules.fulfillment.models import (
    Delivery,
    FulfillmentAttempt,
    FulfillmentTask,
)
from yupay.modules.fulfillment.routes import admin_router, router
from yupay.modules.fulfillment.schemas import (
    DeliveryListOut,
    DeliveryOut,
    FulfillmentAttemptOut,
    FulfillmentTaskListOut,
    FulfillmentTaskOut,
    ManualCompleteIn,
    ManualFailIn,
)
from yupay.modules.fulfillment.service import (
    cancel_task,
    complete_manual_task,
    fail_manual_task,
    get_task_admin,
    list_deliveries_for_order,
    list_tasks_admin,
    process_task,
    retry_task,
    start_for_order,
)
from yupay.modules.fulfillment.suppliers import (
    Fulfiller,
    FulfillerError,
    FulfillerNotIntegratedError,
    FulfillResult,
    FulfillStatus,
    available_suppliers,
    get_fulfiller,
)

__all__ = [
    "Delivery",
    "DeliveryListOut",
    "DeliveryOut",
    "Fulfiller",
    "FulfillerError",
    "FulfillerNotIntegratedError",
    "FulfillResult",
    "FulfillStatus",
    "FulfillmentAttempt",
    "FulfillmentAttemptOut",
    "FulfillmentTask",
    "FulfillmentTaskListOut",
    "FulfillmentTaskOut",
    "ManualCompleteIn",
    "ManualFailIn",
    "admin_router",
    "available_suppliers",
    "cancel_task",
    "complete_manual_task",
    "fail_manual_task",
    "get_fulfiller",
    "get_task_admin",
    "list_deliveries_for_order",
    "list_tasks_admin",
    "process_task",
    "retry_task",
    "router",
    "start_for_order",
]
