from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal, Optional

from src.truefit_core.common.utils import logger
from src.truefit_core.domain.user import User, UserRole
from src.truefit_core.application.ports import (
    UserRepository,
    OrgRepository,
    CandidateProfileRepository,
)

AccountType = Literal["candidate", "org", "plain"]


@dataclass(frozen=True)
class OrgCreateInput:
    name: str
    slug: str
    contact: dict
    billing: dict
    description: str | None = None
    industry: str | None = None
    headcount: str | None = None
    logo_url: str | None = None


@dataclass(frozen=True)
class CandidateProfileInput:
    headline: str | None = None
    bio: str | None = None
    location: str | None = None
    years_experience: int | None = None
    skills: list[str] | None = None


class UserService:
    def __init__(
        self,
        *,
        user_repo: UserRepository,
        org_repo: OrgRepository,
        candidate_profile_repo: CandidateProfileRepository,
    ) -> None:
        self._users = user_repo
        self._orgs = org_repo
        self._candidates = candidate_profile_repo

    async def create_user(
        self,
        *,
        email: str,
        display_name: str | None,
        auth_provider: str,
        provider_subject: str,
        account_type: AccountType = "candidate",
        org: OrgCreateInput | None = None,
        candidate_profile: CandidateProfileInput | None = None,
    ) -> dict:
        """
        Returns a composite dict:
          {
            "user": User,
            "org": {..} | None,
            "candidate_profile": {..} | None,
          }
        """


        email_norm = email.lower().strip()
        existing = await self._users.get_by_email(email_norm)


        print(f"\n\n\nCreating user with email={email_norm} account_type={account_type}\n\n")
        if existing:
            raise ValueError(f"User with email '{email_norm}' already exists")

        # Default behavior: candidate account (creates profile)
        if account_type == "candidate":
            role = UserRole.candidate
        elif account_type == "org":
            # creator of org should be recruiter/admin-ish
            role = UserRole.recruiter
        else:
            # "plain" means no profile created
            role = UserRole.candidate  # or recruiter

        user = User.create(
            email=email_norm,
            display_name=display_name,
            role=role,
            auth_provider=auth_provider,
            provider_subject=provider_subject,
            org_id=None,
        )
        await self._users.save(user)

        created_org = None
        created_candidate_profile = None

        if account_type == "candidate":
            cp = candidate_profile or CandidateProfileInput()
            created_candidate_profile = await self._candidates.create_for_user(
                user_id=user.id,
                headline=cp.headline,
                bio=cp.bio,
                location=cp.location,
                years_experience=cp.years_experience,
                skills=cp.skills or [],
            )
            logger.info(f"Candidate profile created for user {user.id}")

        elif account_type == "org":
            if org is None:
                raise ValueError("org payload is required when account_type='org'")

            # Ensure slug is free (optional; org endpoint might already enforce)
            existing_org = await self._orgs.get_by_slug(org.slug)
            if existing_org:
                raise ValueError(f"Org with slug '{org.slug}' already exists")

            created_org = await self._orgs.create_org(
                created_by=user.id,
                name=org.name,
                slug=org.slug,
                contact=org.contact,
                billing=org.billing,
                description=org.description,
                industry=org.industry,
                headcount=org.headcount,
                logo_url=org.logo_url,
            )

            # Make creator a member (via users.org_id)
            user.set_org(uuid.UUID(created_org["id"]) if isinstance(created_org["id"], str) else created_org["id"])
            await self._users.save(user)

            logger.info(f"Org created: {created_org['id']} by user {user.id}")

        logger.info(f"User created: {user.id} email={user.email} role={user.role.value}")
        return {"user": user, "org": created_org, "candidate_profile": created_candidate_profile}

    async def get_user(self, user_id: uuid.UUID) -> User | None:
        return await self._users.get_by_id(user_id)

    async def get_user_by_email(self, email: str) -> User | None:
        return await self._users.get_by_email(email.lower().strip())

    async def update_user(
        self,
        *,
        user_id: uuid.UUID,
        display_name: str | None = None,
        is_active: bool | None = None,
        role: str | None = None,
        org_id: uuid.UUID | None = None,
    ) -> User:
        user = await self._users.get_by_id(user_id)
        if not user:
            raise ValueError(f"User {user_id} not found")

        if display_name is None and is_active is None and role is None and org_id is None:
            raise ValueError("At least one field must be provided")

        user.update_profile(display_name=display_name, is_active=is_active)

        if role is not None:
            user.role = UserRole(role)

        if org_id is not None:
            user.org_id = org_id
            
        await self._users.save(user)
        return user

    async def join_org(self, *, user_id: uuid.UUID, org_id: uuid.UUID) -> User:
        user = await self._users.get_by_id(user_id)
        if not user:
            raise ValueError(f"User {user_id} not found")

        user.set_org(org_id)
        await self._users.save(user)
        return user

    async def get_or_create_oauth_user(
        self,
        *,
        email: str,
        provider: str,
        provider_subject: str,
        display_name: str | None = None,
    ) -> tuple[User, bool]: #(User, is_new_user)
        """
        Get existing OAuth user or create new one.
        
        This method is used during OAuth authentication flow:
        1. If user with email exists, verify provider_subject matches
        2. If user exists with different provider_subject, update it
        3. If user doesn't exist, create new OAuth user as candidate
        
        Args:
            email: User email (normalized)
            provider: OAuth provider name (e.g., 'firebase', 'google')
            provider_subject: Provider's unique user ID
            display_name: User's display name from provider
        
        Returns:
            User object or None if creation failed
        
        Raises:
            ValueError: If there's a conflict or invalid state
        """

        email_norm = email.lower().strip()
        existing = await self._users.get_by_email(email_norm)

        if existing:
            # Existing user — update provider_subject if changed
            if existing.provider_subject != provider_subject:
                existing.provider_subject = provider_subject
                await self._users.save(existing)
            return existing, False  # ← not new

        # New user
        try:
            user = User.create(
                email=email_norm,
                display_name=display_name,
                role=UserRole.candidate,
                auth_provider=provider,
                provider_subject=provider_subject,
                org_id=None,
            )
            await self._users.save(user)
            await self._candidates.create_for_user(
                user_id=user.id,
                headline=None,
                bio=None,
                location=None,
                years_experience=None,
                skills=[],
            )
            logger.info(f"New OAuth user created: {email_norm}")
            return user, True  # ← is new
        except Exception as e:
            logger.error(f"Error creating OAuth user: {e}")
            raise ValueError(f"Failed to create user: {str(e)}")
        # email_norm = email.lower().strip()
        
        # # Try to get existing user
        # existing_user = await self._users.get_by_email(email_norm)
        
        # if existing_user:
        #     # User exists - verify or update provider info
        #     if existing_user.auth_provider != provider:
        #         logger.warning(
        #             f"User {email_norm} exists with different provider: "
        #             f"{existing_user.auth_provider} vs {provider}"
        #         )
        #         # Could allow this for federated identity, but for now we require same provider
        #         raise ValueError(
        #             f"User already exists with different provider ({existing_user.auth_provider})"
        #         )
            
        #     # Update provider_subject if different (handles provider ID changes)
        #     if existing_user.provider_subject != provider_subject:
        #         logger.info(
        #             f"Updating provider_subject for user {email_norm}"
        #         )
        #         existing_user.provider_subject = provider_subject
        #         await self._users.save(existing_user)
            
        #     # Update display_name if provided and different
        #     if display_name and existing_user.display_name != display_name:
        #         existing_user.display_name = display_name
        #         await self._users.save(existing_user)
            
        #     logger.info(f"OAuth user authenticated: {email_norm}")
        #     return existing_user
        
        # # User doesn't exist - create new OAuth user
        # try:
        #     user = User.create(
        #         email=email_norm,
        #         display_name=display_name,
        #         role=UserRole.candidate,  # Default new OAuth users to candidate
        #         auth_provider=provider,
        #         provider_subject=provider_subject,
        #         org_id=None,
        #     )
        #     await self._users.save(user)
            
        #     # Create candidate profile for new user
        #     await self._candidates.create_for_user(
        #         user_id=user.id,
        #         headline=None,
        #         bio=None,
        #         location=None,
        #         years_experience=None,
        #         skills=[],
        #     )
            
        #     logger.info(f"New OAuth user created: {email_norm}")
        #     return user
        # except Exception as e:
        #     logger.error(f"Error creating OAuth user: {e}")
        #     raise ValueError(f"Failed to create user: {str(e)}")