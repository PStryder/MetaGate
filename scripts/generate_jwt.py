#!/usr/bin/env python3
"""
Generate a JWT token for testing MetaGate authentication.

Usage: python scripts/generate_jwt.py [auth_subject] [--secret SECRET]
"""
import argparse
from datetime import datetime, timezone, timedelta
from jose import jwt


def generate_jwt(
    subject: str,
    secret: str = "change-me-in-production",
    algorithm: str = "HS256",
    expires_hours: int = 24,
) -> str:
    """Generate a JWT token."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(hours=expires_hours),
        "iss": "metagate-test",
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


def main():
    parser = argparse.ArgumentParser(description="Generate JWT for MetaGate testing")
    parser.add_argument(
        "subject",
        nargs="?",
        default="test-subject-001",
        help="Auth subject (default: test-subject-001)",
    )
    parser.add_argument(
        "--secret",
        default="change-me-in-production",
        help="JWT secret key",
    )
    parser.add_argument(
        "--expires",
        type=int,
        default=24,
        help="Token expiration in hours (default: 24)",
    )

    args = parser.parse_args()

    token = generate_jwt(args.subject, args.secret, expires_hours=args.expires)

    print("="*60)
    print("JWT TOKEN GENERATED")
    print("="*60)
    print(f"\nSubject: {args.subject}")
    print(f"Expires in: {args.expires} hours")
    print(f"\nToken:")
    print(f"  {token}")
    print("\nTest bootstrap with:")
    print(f'  curl -X POST http://localhost:8000/v1/bootstrap \\')
    print(f'    -H "Authorization: Bearer {token}" \\')
    print(f'    -H "Content-Type: application/json" \\')
    print(f'    -d \'{{"component_key": "memorygate_main"}}\'')
    print("="*60)


if __name__ == "__main__":
    main()
