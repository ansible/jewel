"""
Email Hijack Detection Command for AAP Gateway

Usage: python manage.py detect_email_hijack

Detects potential email hijacking by analyzing:
  1. Activity stream for email changes
  2. Users with both local and external authenticators
  3. AuthenticatorUser.email vs User.email mismatches
  4. Duplicate emails across users
  5. Email changes made by non-superuser actors
  6. Email changes where the new email matched another user
  7. High-risk combo: email changed + dual authenticators
"""

from collections import defaultdict

from ansible_base.activitystream.models import Entry
from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_plugin
from ansible_base.authentication.models import AuthenticatorUser
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

User = get_user_model()

SEPARATOR = "=" * 90
SUB_SEPARATOR = "-" * 90


class Command(BaseCommand):
    help = "Detect potential email hijacking by scanning the activity stream and authenticator linkages."

    def header(self, title):
        self.stdout.write(f"\n{SEPARATOR}")
        self.stdout.write(f"  {title}")
        self.stdout.write(SEPARATOR)

    def handle(self, *args, **options):
        email_changes = self._check_activity_stream()
        dual_auth_users = self._check_dual_authenticators(
            email_changes,
        )
        mismatches = self._check_email_mismatches()
        duplicates = self._check_duplicate_emails()
        non_super = self._check_non_superuser_changes(
            email_changes,
        )
        suspicious = self._check_email_matches_other_user(
            email_changes,
        )
        high_risk = self._check_high_risk_combo(
            email_changes,
            dual_auth_users,
        )
        self._print_summary(
            email_changes,
            dual_auth_users,
            mismatches,
            duplicates,
            non_super,
            suspicious,
            high_risk,
        )

    # -----------------------------------------------------------------
    # 1. Activity stream email changes
    # -----------------------------------------------------------------
    def _check_activity_stream(self):
        self.header("1. ACTIVITY STREAM: ALL EMAIL CHANGES ON USER OBJECTS")
        user_ct = ContentType.objects.get_for_model(User)
        entries = (
            Entry.objects.filter(
                content_type=user_ct,
                operation="update",
                changes__changed_fields__has_key="email",
            )
            .select_related("created_by")
            .order_by("created")
        )

        records = []
        if not entries.exists():
            self.stdout.write("\n  No email changes found in the activity stream.")
            return records

        self.stdout.write(f"\n  Found {entries.count()} email change(s):\n")
        for entry in entries:
            old_email, new_email = entry.changes["changed_fields"]["email"]
            actor = entry.created_by
            actor_name = actor.username if actor else "SYSTEM/UNKNOWN"
            actor_is_super = actor.is_superuser if actor else None

            try:
                target = User.all_objects.get(pk=entry.object_id)
                target_name = target.username
            except User.DoesNotExist:
                target = None
                target_name = f"[DELETED user pk={entry.object_id}]"

            record = {
                "entry": entry,
                "old_email": old_email,
                "new_email": new_email,
                "actor": actor,
                "actor_name": actor_name,
                "actor_is_super": actor_is_super,
                "target_user": target,
                "target_name": target_name,
                "timestamp": entry.created,
            }
            records.append(record)

            is_self = actor and target and actor.pk == target.pk
            flag = " [SELF-EDIT]" if is_self else ""
            if actor_is_super is False:
                flag += " [NON-SUPERUSER ACTOR]"

            self.stdout.write(f"  [{entry.created}] {actor_name} changed {target_name}'s email{flag}")
            self.stdout.write(f"    Old: {old_email or '(empty)'}")
            self.stdout.write(f"    New: {new_email or '(empty)'}")
            self.stdout.write("")

        return records

    # -----------------------------------------------------------------
    # 2. Users with both local and external authenticators
    # -----------------------------------------------------------------
    def _check_dual_authenticators(self, email_changes):
        self.header("2. USERS WITH LOCAL + EXTERNAL AUTHENTICATORS")
        users_with_auth = defaultdict(lambda: {"local": [], "external": []})
        auth_users = AuthenticatorUser.objects.select_related(
            "user",
            "provider",
        ).all()
        for au in auth_users:
            try:
                plugin = get_authenticator_plugin(
                    au.provider.type,
                )
                auth_type = plugin.type
            except Exception:
                auth_type = "unknown"

            bucket = "local" if auth_type == "local" else "external"
            users_with_auth[au.user_id][bucket].append(
                {
                    "name": au.provider.name,
                    "type": au.provider.type,
                    "uid": au.uid,
                    "email": au.email,
                }
            )

        dual = {uid: data for uid, data in users_with_auth.items() if data["local"] and data["external"]}

        if not dual:
            self.stdout.write("\n  No users found with both local and external authenticators.")
            return dual

        self.stdout.write(f"\n  Found {len(dual)} user(s) with both local and external authenticators:\n")
        changed_pks = {r["target_user"].pk for r in email_changes if r["target_user"]}
        for user_id, data in dual.items():
            try:
                u = User.all_objects.get(pk=user_id)
                uname = u.username
                uemail = u.email
            except User.DoesNotExist:
                uname = f"[DELETED pk={user_id}]"
                uemail = "N/A"

            flag = " *** EMAIL WAS CHANGED ***" if user_id in changed_pks else ""
            self.stdout.write(f"  User: {uname} (pk={user_id}, email={uemail}){flag}")
            for a in data["local"]:
                self.stdout.write(f"    [LOCAL]    {a['name']} | uid={a['uid']} | auth_email={a['email']}")
            for a in data["external"]:
                self.stdout.write(f"    [EXTERNAL] {a['name']} ({a['type']}) | uid={a['uid']} | auth_email={a['email']}")
            self.stdout.write("")

        return dual

    # -----------------------------------------------------------------
    # 3. AuthenticatorUser.email vs User.email mismatches
    # -----------------------------------------------------------------
    def _check_email_mismatches(self):
        self.header("3. AUTHENTICATOR EMAIL vs USER EMAIL MISMATCHES")
        mismatches = []
        qs = (
            AuthenticatorUser.objects.select_related(
                "user",
                "provider",
            )
            .exclude(email__isnull=True)
            .exclude(email="")
        )
        for au in qs:
            if au.user.email and au.email and au.email.lower() != au.user.email.lower():
                mismatches.append(au)

        if not mismatches:
            self.stdout.write("\n  No mismatches found between AuthenticatorUser.email and User.email.")
            return mismatches

        self.stdout.write(f"\n  Found {len(mismatches)} mismatch(es):\n")
        for au in mismatches:
            self.stdout.write(f"  User: {au.user.username} (pk={au.user.pk})")
            self.stdout.write(f"    User.email:              {au.user.email}")
            self.stdout.write(f"    AuthenticatorUser.email:  {au.email}  (authenticator: {au.provider.name})")
            self.stdout.write("")

        return mismatches

    # -----------------------------------------------------------------
    # 4. Duplicate emails across users
    # -----------------------------------------------------------------
    def _check_duplicate_emails(self):
        self.header("4. DUPLICATE EMAILS ACROSS USERS")

        email_to_users = defaultdict(list)
        qs = User.all_objects.exclude(
            email__isnull=True,
        ).exclude(email="")
        for u in qs:
            email_to_users[u.email.lower()].append(u)

        dupes = {email: users for email, users in email_to_users.items() if len(users) > 1}

        if not dupes:
            self.stdout.write("\n  No duplicate emails found across users.")
            return dupes

        self.stdout.write(f"\n  Found {len(dupes)} email(s) shared by multiple users:\n")
        for email, users in dupes.items():
            self.stdout.write(f"  Email: {email}")
            for u in users:
                self.stdout.write(f"    - {u.username} (pk={u.pk}, is_superuser={u.is_superuser})")
            self.stdout.write("")

        return dupes

    # -----------------------------------------------------------------
    # 5. Email changes by non-superuser actors
    # -----------------------------------------------------------------
    def _check_non_superuser_changes(self, email_changes):
        self.header("5. EMAIL CHANGES BY NON-SUPERUSER ACTORS")
        non_super = [r for r in email_changes if r["actor_is_super"] is False]

        if not non_super:
            self.stdout.write("\n  No email changes by non-superuser actors found.")
            return non_super

        self.stdout.write(f"\n  Found {len(non_super)} email change(s) by non-superuser actors:\n")
        for r in non_super:
            is_self = r["actor"] and r["target_user"] and r["actor"].pk == r["target_user"].pk
            edit_type = "SELF-EDIT" if is_self else "EDITED ANOTHER USER"
            self.stdout.write(f"  [{r['timestamp']}] Actor: {r['actor_name']} ({edit_type})")
            self.stdout.write(f"    Target: {r['target_name']}")
            self.stdout.write(f"    {r['old_email'] or '(empty)'} -> {r['new_email'] or '(empty)'}")
            self.stdout.write("")

        return non_super

    # -----------------------------------------------------------------
    # 6. Email changed to match another user
    # -----------------------------------------------------------------
    def _check_email_matches_other_user(self, email_changes):
        self.header("6. EMAIL CHANGES THAT MATCHED ANOTHER EXISTING USER'S EMAIL")
        suspicious = []
        for r in email_changes:
            if not r["new_email"]:
                continue
            others = User.all_objects.filter(
                email__iexact=r["new_email"],
            ).exclude(pk=r["entry"].object_id)
            if others.exists():
                suspicious.append((r, list(others)))

        if not suspicious:
            self.stdout.write("\n  No email changes resulted in a match with another user's current email.")
            self.stdout.write("  (Note: checks current state; the match may have existed only at the time of change.)")
            return suspicious

        self.stdout.write(f"\n  Found {len(suspicious)} suspicious match(es):\n")
        for r, matched_users in suspicious:
            self.stdout.write(f"  [{r['timestamp']}] {r['actor_name']} changed {r['target_name']}'s email")
            self.stdout.write(f"    New email: {r['new_email']}")
            self.stdout.write("    MATCHES these other users:")
            for mu in matched_users:
                self.stdout.write(f"      - {mu.username} (pk={mu.pk})")
            self.stdout.write("")

        return suspicious

    # -----------------------------------------------------------------
    # 7. High-risk: email changed + dual authenticators
    # -----------------------------------------------------------------
    def _check_high_risk_combo(
        self,
        email_changes,
        dual_auth_users,
    ):
        self.header("7. HIGH-RISK: EMAIL CHANGED + LOCAL+EXTERNAL AUTHENTICATORS")
        high_risk = [r for r in email_changes if r["target_user"] and r["target_user"].pk in dual_auth_users]

        if not high_risk:
            self.stdout.write("\n  No high-risk combinations found.")
            return high_risk

        self.stdout.write(f"\n  Found {len(high_risk)} high-risk user(s):\n")
        for r in high_risk:
            uid = r["target_user"].pk
            data = dual_auth_users[uid]
            self.stdout.write(f"  [{r['timestamp']}] {r['target_name']} (pk={uid})")
            self.stdout.write(f"    Email changed: {r['old_email'] or '(empty)'} -> {r['new_email'] or '(empty)'}")
            self.stdout.write(f"    Changed by: {r['actor_name']} (superuser={r['actor_is_super']})")
            self.stdout.write("    Authenticators:")
            for a in data["local"]:
                self.stdout.write(f"      [LOCAL]    {a['name']} | uid={a['uid']}")
            for a in data["external"]:
                self.stdout.write(f"      [EXTERNAL] {a['name']} | uid={a['uid']}")
            self.stdout.write("")

        return high_risk

    # -----------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------
    def _print_summary(
        self,
        email_changes,
        dual_auth_users,
        mismatches,
        duplicates,
        non_super,
        suspicious,
        high_risk,
    ):
        self.header("SUMMARY")
        self.stdout.write(f"\n  Total email changes in activity stream:      {len(email_changes)}")
        self.stdout.write(f"  Users with local + external auth:             {len(dual_auth_users)}")
        self.stdout.write(f"  AuthUser vs User email mismatches:            {len(mismatches)}")
        self.stdout.write(f"  Duplicate emails across users:                {len(duplicates)}")
        self.stdout.write(f"  Email changes by non-superusers:              {len(non_super)}")
        self.stdout.write(f"  Email changes matching another user:          {len(suspicious)}")
        self.stdout.write(f"  High-risk (changed email + dual auth):        {len(high_risk)}")
        self.stdout.write("")

        if any([non_super, suspicious, high_risk]):
            self.stdout.write("  *** POTENTIAL ISSUES DETECTED - REVIEW FLAGGED ITEMS ABOVE ***")
        else:
            self.stdout.write("  No obvious indicators of email hijacking detected.")

        self.stdout.write(f"\n{SEPARATOR}\n")
