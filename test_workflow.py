import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.models import SessionLocal
from app.services.chat_service import ChatService

def main():
    db = SessionLocal()
    try:
        print("\n--- TEST 1: Manager command /assign-task with dynamic T+2 and T+3 dates ---")
        res1 = ChatService.handle_message(
            db=db,
            user_email="manager@techcorp.internal",
            text='/assign-task cohort=1 title="Task 2: Redis Caching" spec="Implement distributed cache layer with invalidation and fallback."'
        )
        print("Reply:\n", res1["reply"])

        print("\n--- TEST 2: Conversational Task Assignment ---")
        res2 = ChatService.handle_message(
            db=db,
            user_email="manager@techcorp.internal",
            text='Assign Task 3 to Cohort 1: spec="Build Kafka Event Consumer with exponential backoff retry."'
        )
        print("Reply:\n", res2["reply"])

        print("\n--- TEST 3: Review & Guidance Agent (/review-task) ---")
        res3 = ChatService.handle_message(
            db=db,
            user_email="mentor1@techcorp.internal",
            text='/review-task intern_id=1 task_id=2 code="https://github.com/intern001/caching" notes="Unit tests are missing for Redis connection timeout; also sanitize error logs to avoid leaking internal host IPs."'
        )
        print("Reply:\n", res3["reply"])

        print("\n--- TEST 4: Cohort Leaderboard (/leaderboard) ---")
        res4 = ChatService.handle_message(
            db=db,
            user_email="manager@techcorp.internal",
            text='/leaderboard cohort=1 limit=5'
        )
        print("Reply:\n", res4["reply"])

        print("\n--- TEST 5: 3-Month Milestone Evaluation & Certification Verdict (/final-verdict) ---")
        res5 = ChatService.handle_message(
            db=db,
            user_email="manager@techcorp.internal",
            text='/final-verdict intern_id=1'
        )
        print("Reply:\n", res5["reply"])

        print("\n--- ALL TESTS COMPLETED SUCCESSFULLY ---")
    finally:
        db.close()

if __name__ == "__main__":
    main()
