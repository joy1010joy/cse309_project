"""Firestore repositories (database access).

A repository layer keeps the rest of the code agnostic of the storage
implementation.  Tests substitute :class:`FakeFirestore` for the real
``firestore.Client`` so they do not need network access.
"""