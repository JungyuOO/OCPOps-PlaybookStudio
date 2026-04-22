"""Windows Task Scheduler registration helpers for gold foundry routines."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from play_book_studio.config.settings import Settings

from .foundry_orchestrator import FoundryProfile, load_foundry_profiles


DAY_NAME_MAP = {
    "Mon": "MON",
    "Tue": "TUE",
    "Wed": "WED",
    "Thu": "THU",
    "Fri": "FRI",
    "Sat": "SAT",
    "Sun": "SUN",
}
FULL_WEEK = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass(frozen=True)
class FoundryScheduledTask:
    profile_id: str
    task_name: str
    command: str
    log_path: str
    schedule_args: tuple[str, ...]
    schtasks_args: tuple[str, ...]
def _schedule_args(profile: FoundryProfile) -> tuple[str, ...]:
    if profile.cadence == "hourly":
        start_time = f"00:{int(profile.minute or 0):02d}"
        return ("/SC", "HOURLY", "/MO", str(profile.interval_hours or 1), "/ST", start_time)

    if profile.cadence == "weekly":
        days = ",".join(DAY_NAME_MAP[day] for day in profile.days)
        return ("/SC", "WEEKLY", "/D", days, "/ST", str(profile.time or "00:00"))

    if profile.cadence == "daily":
        if profile.days and tuple(profile.days) != FULL_WEEK:
            days = ",".join(DAY_NAME_MAP[day] for day in profile.days)
            return ("/SC", "WEEKLY", "/D", days, "/ST", str(profile.time or "00:00"))
        return ("/SC", "DAILY", "/ST", str(profile.time or "00:00"))

    raise ValueError(f"unsupported cadence for scheduler registration: {profile.cadence}")


def _command_string(
    settings: Settings,
    *,
    profile_id: str,
    retries: int,
    retry_delay_seconds: int,
) -> str:
    wrapper_path = settings.root_dir / "scripts" / "run_foundry_task.ps1"
    pwsh_path = Path(r"C:\Program Files\PowerShell\7\pwsh.exe")
    return (
        f'"{pwsh_path}" -NoLogo -NoProfile -ExecutionPolicy Bypass '
        f'-File "{wrapper_path}" -Profile {profile_id} '
        f"-Retries {retries} -RetryDelaySeconds {retry_delay_seconds}"
    )


def build_scheduled_task(
    settings: Settings,
    profile: FoundryProfile,
    *,
    task_prefix: str = "PlayBookStudio\\Foundry",
    retries: int = 2,
    retry_delay_seconds: int = 900,
    replace: bool = True,
) -> FoundryScheduledTask:
    resolved_log_dir = (settings.root_dir / "reports" / "build_logs" / "task_scheduler").resolve()
    log_path = resolved_log_dir / f"{profile.profile_id}.log"
    normalized_prefix = task_prefix.rstrip("\\")
    task_name = f"{normalized_prefix}\\{profile.profile_id}"
    schedule_args = _schedule_args(profile)
    command = _command_string(
        settings,
        profile_id=profile.profile_id,
        retries=retries,
        retry_delay_seconds=retry_delay_seconds,
    )
    schtasks_args = [
        "schtasks",
        "/Create",
        "/TN",
        task_name,
        "/TR",
        command,
        *schedule_args,
    ]
    if replace:
        schtasks_args.append("/F")
    return FoundryScheduledTask(
        profile_id=profile.profile_id,
        task_name=task_name,
        command=command,
        log_path=str(log_path),
        schedule_args=tuple(schedule_args),
        schtasks_args=tuple(schtasks_args),
    )


def build_foundry_schedule_tasks(
    settings: Settings,
    *,
    selected_profiles: tuple[str, ...] | None = None,
    task_prefix: str = "PlayBookStudio\\Foundry",
    retries: int = 2,
    retry_delay_seconds: int = 900,
    replace: bool = True,
) -> list[FoundryScheduledTask]:
    profiles = load_foundry_profiles(settings)
    profile_ids = selected_profiles or tuple(profiles)
    tasks: list[FoundryScheduledTask] = []
    for profile_id in profile_ids:
        if profile_id not in profiles:
            raise KeyError(f"unknown foundry profile for scheduler registration: {profile_id}")
        tasks.append(
            build_scheduled_task(
                settings,
                profiles[profile_id],
                task_prefix=task_prefix,
                retries=retries,
                retry_delay_seconds=retry_delay_seconds,
                replace=replace,
            )
        )
    return tasks


def register_foundry_schedule_tasks(tasks: list[FoundryScheduledTask]) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for task in tasks:
        subprocess.run(task.schtasks_args, check=True, capture_output=True, text=True)
        results.append(
            {
                "profile_id": task.profile_id,
                "task_name": task.task_name,
                "log_path": task.log_path,
                "command": task.command,
            }
        )
    return results
