"""Interactive administrative mapping and non-production provider walkthrough."""

import argparse
import getpass
import sys
from uuid import UUID

from pydantic import SecretStr

from trading_api.logging import configure_logging
from trading_auth.config import load_settings
from trading_auth.service import Authenticator
from trading_auth.supabase import SupabaseProvider
from trading_db.enrollment import provision_owner, revoke_owner
from trading_db.identities import IdentityDatabase
from trading_db.local import development


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["provision-owner", "smoke", "init-session-key", "revoke-owner"]
    )
    args = parser.parse_args()
    configure_logging()
    try:
        if args.action == "init-session-key":
            from trading_auth.local import initialize_key

            initialize_key()
            print("Private local session key created; existing keys are never overwritten.")
            return 0
        # Never emit an enrollment seed into redirected output or an automation log.
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise ValueError("Interactive terminal required")
        config = load_settings()
        service = development()
        if args.action == "revoke-owner":
            subject = UUID(getpass.getpass("Supabase user UUID to revoke locally: "))
            revoke_owner(service.url("bootstrap"), service.project, config.issuer, subject)
            print("Local sessions revoked. Provider sessions must be revoked separately.")
            return 0
        if args.action == "provision-owner":
            subject = UUID(getpass.getpass("Verified Supabase user UUID: "))
            provision_owner(service.url("bootstrap"), service.project, config.issuer, subject)
            print("Owner mapping created. MFA is required before authentication can complete.")
            return 0
        identities = IdentityDatabase(service.url("auth"), service.project)
        provider = SupabaseProvider(config)
        try:
            authenticator = Authenticator(provider, identities)
            email = getpass.getpass("Development account email: ")
            password = SecretStr(getpass.getpass("Password: "))
            with authenticator.begin(email, password) as attempt:
                password = SecretStr("")
                enrollment = attempt.prepare_mfa()
                if enrollment is not None:
                    print("Add this setup key to your authenticator (TOTP, 6 digits, 30 seconds).")
                    print("Development setup key: " + enrollment.secret.get_secret_value())
                    print(
                        "Keep this terminal private; never copy its contents into logs or issues."
                    )
                    enrollment = None
                attempt.verify_mfa(SecretStr(getpass.getpass("Authenticator code: ")))
            print(
                "Password and MFA verified. Provider session discarded; "
                "no workspace session created."
            )
        finally:
            provider.close()
            identities.close()
        return 0
    except Exception, KeyboardInterrupt:
        print(
            "Authentication operation failed; see docs/authentication-foundation.md.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
