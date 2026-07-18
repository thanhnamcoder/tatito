import sys
from auto import scheduler, check_scheduler_status

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in {"--status", "status"}:
        status = check_scheduler_status()
        print(status["message"])
        sys.exit(0 if status["running"] else 1)

    scheduler()