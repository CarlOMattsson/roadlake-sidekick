"""The transaction handle that persistence ports pass to their callers.

Application services never open sessions; `transaction(operation)` hands them one. Naming the type
here keeps the ports (Protocols in the application layer) free of `Any` without making the
application layer import the persistence package.
"""

from sqlalchemy.orm import Session

TxSession = Session
"""The open unit of work inside `transaction(...)`; owner scoping stays in the store methods."""
