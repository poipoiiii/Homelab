from labtools.tools.bills import recent_expenses
from labtools.tools.containers import list_services
from labtools.tools.disk import disk_usage


def run_selftest() -> None:
    print("== services ==")
    print(list_services())
    print("== disk ==")
    print(disk_usage())
    print("== recent expenses ==")
    print(recent_expenses(3))
