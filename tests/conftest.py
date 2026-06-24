from typing import Callable

import pytest

# The legacy tau2-bench fixtures below require the `tau2` package, which is not
# vendored in this repo. Import it lazily so that collecting non-tau2 tests
# (dashboard, FDRC, adapters) does not crash the whole suite. The tau2 fixtures
# raise a skip if used without the package installed.
try:  # pragma: no cover - environment dependent
    from tau2.data_model.tasks import Task
    from tau2.environment.environment import Environment
    from tau2.registry import registry
    from tau2.run import get_tasks

    _TAU2_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - environment dependent
    _TAU2_AVAILABLE = False
    Task = object  # type: ignore[assignment,misc]
    Environment = object  # type: ignore[assignment,misc]
    registry = None  # type: ignore[assignment]
    get_tasks = None  # type: ignore[assignment]


@pytest.fixture
def domain_name():
    return "mock"


@pytest.fixture
def get_environment() -> Callable[[], Environment]:
    return registry.get_env_constructor("mock")


@pytest.fixture
def base_task() -> Task:
    return get_tasks("mock", task_ids=["create_task_1"])[0]


@pytest.fixture
def task_with_env_assertions() -> Task:
    return get_tasks("mock", task_ids=["create_task_1_with_env_assertions"])[0]


@pytest.fixture
def task_with_message_history() -> Task:
    return get_tasks("mock", task_ids=["update_task_with_message_history"])[0]


@pytest.fixture
def task_with_initialization_data() -> Task:
    return get_tasks("mock", task_ids=["update_task_with_initialization_data"])[0]


@pytest.fixture
def task_with_initialization_actions() -> Task:
    return get_tasks("mock", task_ids=["update_task_with_initialization_actions"])[0]


@pytest.fixture
def task_with_history_and_env_assertions() -> Task:
    return get_tasks("mock", task_ids=["update_task_with_history_and_env_assertions"])[
        0
    ]


@pytest.fixture
def task_with_action_checks() -> Task:
    return get_tasks("mock", task_ids=["impossible_task_1"])[0]
