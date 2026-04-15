from unittest.mock import patch

import pytest
from ansible_base.rbac.models import DABContentType, DABPermission, RoleDefinition
from ansible_base.resource_registry.models import Resource, ResourceType
from django.db import models
from rest_framework.exceptions import ValidationError

from aap_gateway_api.models import Organization, User
from aap_gateway_api.resource_api import GatewayRoleDefinitionType, GetOrCreateProcessor


@pytest.mark.django_db
class TestGatewayRoleDefinitionType:
    """Test the gatewayRoleDefinitionType serializer in isolation"""

    @pytest.fixture
    def organization_content_type(self):
        """Get or create a content type for organizations"""
        return DABContentType.objects.get_for_model(Organization)

    @pytest.fixture
    def awx_content_type(self):
        """Get or create a content type for awx resources"""
        content_type, created = DABContentType.objects.get_or_create(
            service='awx',
            model='project',
            defaults={
                'id': (DABContentType.objects.aggregate(max_id=models.Max('id'))['max_id'] or 0) + 1,
                'app_label': 'awx',
                'api_slug': 'awx.project',
                'pk_field_type': 'integer',
            },
        )
        return content_type

    @pytest.fixture
    def hub_content_type(self):
        """Get or create a content type for hub resources"""
        content_type, created = DABContentType.objects.get_or_create(
            service='hub',
            model='collection',
            defaults={
                'id': (DABContentType.objects.aggregate(max_id=models.Max('id'))['max_id'] or 0) + 1,
                'app_label': 'galaxy_ng',
                'api_slug': 'hub.collection',
                'pk_field_type': 'integer',
            },
        )
        return content_type

    @pytest.fixture
    def eda_content_type(self):
        """Get or create a content type for eda resources"""
        content_type, created = DABContentType.objects.get_or_create(
            service='eda',
            model='rulebook',
            defaults={
                'id': (DABContentType.objects.aggregate(max_id=models.Max('id'))['max_id'] or 0) + 1,
                'app_label': 'aap_eda',
                'api_slug': 'eda.rulebook',
                'pk_field_type': 'integer',
            },
        )
        return content_type

    @pytest.fixture
    def shared_permissions(self, organization_content_type):
        """Create shared service permissions"""
        permissions = []
        permission_data = [
            ('view_organization', 'shared.view_organization'),
            ('change_organization', 'shared.change_organization'),
            ('delete_organization', 'shared.delete_organization'),
        ]

        for codename, api_slug in permission_data:
            perm = DABPermission.objects.get(api_slug=api_slug)
            permissions.append(perm)

        return permissions

    @pytest.fixture
    def awx_permissions(self, awx_content_type):
        """Create awx service permissions"""
        permissions = []
        permission_data = [
            ('view_project', 'awx.view_project'),
            ('change_project', 'awx.change_project'),
            ('execute_project', 'awx.execute_project'),
        ]

        for codename, api_slug in permission_data:
            perm, created = DABPermission.objects.get_or_create(
                api_slug=api_slug,
                defaults={
                    'name': codename,
                    'codename': codename,
                    'content_type': awx_content_type,
                },
            )
            permissions.append(perm)

        return permissions

    @pytest.fixture
    def hub_permissions(self, hub_content_type):
        """Create hub service permissions"""
        permissions = []
        permission_data = [
            ('view_collection', 'hub.view_collection'),
            ('upload_collection', 'hub.upload_collection'),
        ]

        for codename, api_slug in permission_data:
            perm, created = DABPermission.objects.get_or_create(
                api_slug=api_slug,
                defaults={
                    'name': codename,
                    'codename': codename,
                    'content_type': hub_content_type,
                },
            )
            permissions.append(perm)

        return permissions

    @pytest.fixture
    def eda_permissions(self, eda_content_type):
        """Create eda service permissions"""
        permissions = []
        permission_data = [
            ('view_rulebook', 'eda.view_rulebook'),
            ('run_rulebook', 'eda.run_rulebook'),
        ]

        for codename, api_slug in permission_data:
            perm, created = DABPermission.objects.get_or_create(
                api_slug=api_slug,
                defaults={
                    'name': codename,
                    'codename': codename,
                    'content_type': eda_content_type,
                },
            )
            permissions.append(perm)

        return permissions

    @pytest.fixture
    def role_definition(self, organization_content_type):
        """Create a RoleDefinition for testing"""
        return RoleDefinition.objects.create(
            name='Test Role',
            description='A test role',
            content_type=organization_content_type,
        )

    def test_create_role_definition_with_permissions(self, shared_permissions, awx_permissions):
        """Test creating a role definition with permissions"""
        permission_slugs = ['shared.view_organization', 'awx.view_project']
        data = {
            'name': 'Test Role',
            'description': 'A test role',
            'managed': False,
            'permissions': permission_slugs,
        }

        serializer = GatewayRoleDefinitionType(data=data)
        assert serializer.is_valid(), f"Serializer errors: {serializer.errors}"

        # Actually create the role definition using the resource_registry stuff
        processor = serializer.get_processor()(RoleDefinition())
        processor.save(serializer.validated_data, is_new=True)
        role_def = processor.instance

        # Verify the created object
        assert role_def.name == 'Test Role'
        assert role_def.description == 'A test role'
        assert role_def.managed is False

        # Verify permissions were set correctly
        role_permissions = role_def.permissions.all()
        permission_api_slugs = {p.api_slug for p in role_permissions}
        assert permission_api_slugs == {'shared.view_organization', 'awx.view_project'}

    def test_create_role_definition_with_invalid_permissions(self):
        """Test creating a role definition with non-existent permissions"""
        data = {
            'name': 'Test Role',
            'description': 'A test role',
            'managed': False,
            'permissions': ['nonexistent.permission'],
        }

        # The serializer should not be valid due to DoesNotExist error
        with pytest.raises(DABPermission.DoesNotExist):
            Resource.create_resource(resource_type=ResourceType.objects.get(name='shared.roledefinition'), resource_data=data)

    def test_update_role_definition_basic_merge(self, role_definition, shared_permissions, awx_permissions):
        """Test updating a role definition with nuanced behavior (shared + awx = 2 services)"""
        role_definition.permissions.set([shared_permissions[0], awx_permissions[0]])  # view and view

        # Update with new permissions from the same 2 services
        # This should trigger nuanced behavior since we have exactly shared + awx
        data = {
            'permissions': ['shared.change_organization', 'awx.change_project'],
        }

        # Actually update the role definition using the serializer and processor
        role_definition.resource.update_resource(data, partial=True)

        # With nuanced behavior: awx permissions get replaced, shared get merged
        assert {p.api_slug for p in role_definition.permissions.all()} == {
            'shared.change_organization',  # new shared (replacew shared.view_organization)
            'awx.change_project',  # new awx (replaces awx.view_project)
        }

    def test_update_role_definition_block_multi_service(self, role_definition, shared_permissions, awx_permissions, hub_permissions):
        """Test updating a role definition with standard merge behavior (3+ services)"""
        role_definition.permissions.set([shared_permissions[0], awx_permissions[0]])  # view and view

        # Update with new permissions from 3 services (not supported via resources)
        data = {
            'permissions': ['shared.change_organization', 'awx.change_project', 'hub.view_collection'],
        }

        with pytest.raises(ValidationError) as exc:
            role_definition.resource.update_resource(data, partial=True)

        assert 'Not expected to set permissions for more than 1 non-shared service' in str(exc)

    def test_nuanced_behavior_shared_plus_one_service(self, role_definition, shared_permissions, awx_permissions, hub_permissions):
        """Test nuanced behavior when updating with shared + one other service"""
        # Set up initial permissions from multiple services
        role_definition.permissions.set(
            [
                shared_permissions[0],  # shared.view_organization
                shared_permissions[1],  # shared.change_organization
                awx_permissions[0],  # awx.view_project
                awx_permissions[1],  # awx.change_project
                awx_permissions[2],  # awx.execute_project
                hub_permissions[0],  # hub.view_collection (should be preserved)
            ]
        )

        # Update with only shared + awx permissions (2 services, one being shared)
        data = {
            'permissions': [
                'shared.view_organization',  # keep existing shared
                'shared.delete_organization',  # add new shared
                'awx.view_project',  # keep this awx permission
                # Note: awx.change_project and awx.execute_project should be removed
                # Note: hub.view_collection should be preserved (different service)
            ],
        }

        role_definition.resource.update_resource(data, partial=True)

        assert {p.api_slug for p in role_definition.permissions.all()} == {
            'shared.view_organization',  # existing shared (kept), replaces change_organization
            'shared.delete_organization',  # new shared
            'awx.view_project',  # kept awx permission
            # awx.change_project and awx.execute_project should be removed
            'hub.view_collection',  # preserved from different service
        }

    def test_serialization_to_representation(self, role_definition, shared_permissions, awx_permissions):
        """Test that permissions are properly serialized back to API slugs"""
        role_definition.permissions.set([shared_permissions[0], awx_permissions[0]])

        serializer = GatewayRoleDefinitionType(instance=role_definition)
        data = serializer.data

        assert 'permissions' in data
        assert set(data['permissions']) == {'shared.view_organization', 'awx.view_project'}

    def test_update_without_permissions(self, role_definition):
        role_definition.permissions.set([])

        data = {'name': 'new rd name'}

        role_definition.resource.update_resource(data, partial=True)

        role_definition.refresh_from_db()
        assert role_definition.name == 'new rd name'
        assert list(role_definition.permissions.all()) == []

    def test_duplicate_permissions_handling(self, shared_permissions, awx_permissions):
        """Test that duplicate permissions are handled correctly"""
        data = {
            'name': 'Test Role',
            'description': 'A test role',
            'managed': False,
            'permissions': [
                'shared.view_organization',
                'shared.view_organization',  # duplicate
                'awx.view_project',
            ],
        }

        resource = Resource.create_resource(resource_type=ResourceType.objects.get(name='shared.roledefinition'), resource_data=data)

        # Should deduplicate
        assert {p.api_slug for p in resource.content_object.permissions.all()} == {'shared.view_organization', 'awx.view_project'}

    def test_role_definition_with_create_from_permissions_pattern(self, shared_permissions, awx_permissions, organization_content_type):
        """Test the pattern for creating role definitions with permissions similar to RoleDefinition.create_from_permissions"""
        permission_slugs = ['shared.view_organization', 'awx.view_project']

        # Simulate what create_from_permissions would do
        serializer_data = {
            'name': 'Custom Role',
            'description': 'Created with permissions',
            'managed': False,
            'content_type': organization_content_type.api_slug,  # Use api_slug
            'permissions': permission_slugs,
        }

        resource = Resource.create_resource(resource_type=ResourceType.objects.get(name='shared.roledefinition'), resource_data=serializer_data)

        assert {p.api_slug for p in resource.content_object.permissions.all()} == {'shared.view_organization', 'awx.view_project'}

    def test_validate_permissions_with_nonexistent_slugs(self, organization_content_type):
        """Test handling of permission slugs that don't exist in the database"""
        data = {
            'name': 'Test Role',
            'managed': False,
            'permissions': ['nonexistent.permission', 'shared.view_organization'],
        }

        serializer = GatewayRoleDefinitionType(data=data)

        # The validation should raise a DoesNotExist exception
        with pytest.raises(DABPermission.DoesNotExist) as exc_info:
            serializer.is_valid(raise_exception=True)

        # Verify the error message contains the missing permission
        assert 'nonexistent.permission' in str(exc_info.value)

    def test_nuanced_behavior_complex_scenario(self, role_definition, shared_permissions, awx_permissions, hub_permissions, eda_permissions):
        """Test complex scenario with nuanced behavior"""
        # Set up initial permissions with multiple services
        role_definition.permissions.set(
            [
                shared_permissions[0],  # shared.view_organization
                shared_permissions[1],  # shared.change_organization
                awx_permissions[0],  # awx.view_project
                awx_permissions[1],  # awx.change_project
                awx_permissions[2],  # awx.execute_project
                hub_permissions[0],  # hub.view_collection
                eda_permissions[0],  # eda.view_rulebook
            ]
        )

        # Update with shared + hub only (triggering nuanced behavior for hub)
        data = {
            'permissions': [
                'shared.view_organization',  # keep existing
                'shared.delete_organization',  # add new shared
                'hub.upload_collection',  # new hub permission
                # Note: hub.view_collection should be removed (not in new list)
                # Note: awx and eda permissions should be preserved (different services)
            ],
        }

        role_definition.resource.update_resource(data, partial=True)

        assert {p.api_slug for p in role_definition.permissions.all()} == {
            'shared.view_organization',  # existing shared (kept)
            # shared.change_organization should be removed, not in new list
            'shared.delete_organization',  # new shared
            'hub.upload_collection',  # new hub
            # hub.view_collection should be removed (was existing, not in new list)
            'awx.view_project',  # preserved (different service)
            'awx.change_project',  # preserved (different service)
            'awx.execute_project',  # preserved (different service)
            'eda.view_rulebook',  # preserved (different service)
        }

    def test_create_from_permissions_full_workflow(self, shared_permissions, awx_permissions, organization_content_type):
        """Test complete workflow similar to RoleDefinition.objects.create_from_permissions"""
        permission_slugs = ['shared.view_organization', 'shared.change_organization', 'awx.view_project']

        serializer_data = {
            'name': 'Integration Role',
            'description': 'Role created through serializer',
            'managed': False,
            'content_type': organization_content_type.api_slug,  # Use api_slug
            'permissions': permission_slugs,
        }

        resource = Resource.create_resource(resource_type=ResourceType.objects.get(name='shared.roledefinition'), resource_data=serializer_data)

        # Step 4: Verify the created role definition
        assert resource.content_object.name == 'Integration Role'
        assert resource.content_object.description == 'Role created through serializer'
        assert resource.content_object.content_type == organization_content_type

        # Step 5: Verify permissions were set correctly by the serializer
        assert {p.api_slug for p in resource.content_object.permissions.all()} == {'shared.view_organization', 'shared.change_organization', 'awx.view_project'}

    def test_field_level_validation_edge_cases(self, shared_permissions):
        """Test edge cases in field-level validation"""
        # Test with None permissions
        with pytest.raises(ValidationError):
            serializer = GatewayRoleDefinitionType(data={'permissions': None})
            serializer.is_valid(raise_exception=True)

        # Test with non-list permissions
        with pytest.raises(ValidationError):
            serializer = GatewayRoleDefinitionType(data={'permissions': 'not-a-list'})
            serializer.is_valid(raise_exception=True)

        # Test with mixed valid and invalid permissions
        with pytest.raises(DABPermission.DoesNotExist):
            serializer = GatewayRoleDefinitionType(data={'permissions': ['shared.view_organization', 'invalid.permission']})
            serializer.is_valid(raise_exception=True)

    def test_performance_with_many_permissions(self, organization_content_type):
        """Test serializer performance with a large number of permissions"""
        # Create many permissions
        permissions = []
        permission_slugs = []
        for i in range(50):
            api_slug = f'shared.test_permission_{i}'
            perm, created = DABPermission.objects.get_or_create(
                api_slug=api_slug,
                defaults={
                    'name': f'test_permission_{i}',
                    'codename': f'test_permission_{i}',
                    'content_type': organization_content_type,
                },
            )
            permissions.append(perm)
            permission_slugs.append(perm.api_slug)

        # Test creation with many permissions
        data = {
            'name': 'Performance Test Role',
            'managed': False,
            'permissions': permission_slugs,
        }

        resource = Resource.create_resource(resource_type=ResourceType.objects.get(name='shared.roledefinition'), resource_data=data)

        assert len(resource.content_object.permissions.all()) == 50

        # Test that all permissions are correctly converted
        assert {p.api_slug for p in resource.content_object.permissions.all()} == set(permission_slugs)


@pytest.mark.django_db
class TestGetOrCreateProcessorSerializerValidation:
    """Verify that GetOrCreateProcessor routes reverse-sync
    payloads through the Gateway's own serializers so that all
    business rules are enforced."""

    @pytest.fixture
    def target_user(self):
        return User.objects.create_user(
            username="target_user",
            email="original@example.com",
            password="password123",
        )

    @pytest.fixture
    def superuser(self):
        return User.objects.create_user(
            username="admin_user",
            email="admin@example.com",
            password="password123",
            is_superuser=True,
        )

    @pytest.fixture
    def regular_user(self):
        return User.objects.create_user(
            username="regular_user",
            email="regular@example.com",
            password="password123",
        )

    @pytest.mark.parametrize(
        "requesting_user_fixture, new_email, expected_email",
        [
            pytest.param(
                "superuser",
                "new@example.com",
                "new@example.com",
                id="superuser-can-change-email",
            ),
            pytest.param(
                "regular_user",
                "hijacked@example.com",
                "original@example.com",
                id="regular-user-email-stripped",
            ),
            pytest.param(
                None,
                "synced@example.com",
                "synced@example.com",
                id="no-requesting-user-allowed",
            ),
        ],
    )
    def test_email_policy_on_update(
        self,
        request,
        target_user,
        requesting_user_fixture,
        new_email,
        expected_email,
    ):
        requesting_user = request.getfixturevalue(requesting_user_fixture) if requesting_user_fixture else None
        processor = GetOrCreateProcessor(target_user)

        with patch(
            "aap_gateway_api.resource_api.get_current_user",
            return_value=requesting_user,
        ):
            processor.save(
                {"email": new_email, "first_name": "Updated"},
                is_new=False,
            )

        target_user.refresh_from_db()
        assert target_user.email == expected_email
        assert target_user.first_name == "Updated"

    def test_same_email_is_always_allowed(self, target_user, regular_user):
        """Submitting the same email should not be blocked."""
        processor = GetOrCreateProcessor(target_user)

        with patch(
            "aap_gateway_api.resource_api.get_current_user",
            return_value=regular_user,
        ):
            processor.save(
                {
                    "email": "original@example.com",
                    "first_name": "Updated",
                },
                is_new=False,
            )

        target_user.refresh_from_db()
        assert target_user.email == "original@example.com"
        assert target_user.first_name == "Updated"

    def test_email_policy_on_post_existing_user(self, target_user, regular_user):
        """POST (is_new=True) with existing user should still
        enforce validation."""
        processor = GetOrCreateProcessor(User(username="target_user"))

        with patch(
            "aap_gateway_api.resource_api.get_current_user",
            return_value=regular_user,
        ):
            result = processor.save(
                {
                    "username": "target_user",
                    "email": "hijacked@example.com",
                    "first_name": "PostUpdated",
                },
                is_new=True,
            )

        result.refresh_from_db()
        assert result.email == "original@example.com"
        assert result.first_name == "PostUpdated"

    def test_non_user_model_passes_through(self):
        """Organization updates should pass through the
        OrganizationSerializer without issue."""
        org = Organization.objects.create(name="test_org", description="old")
        processor = GetOrCreateProcessor(org)
        processor.save(
            {"description": "new"},
            is_new=False,
        )
        org.refresh_from_db()
        assert org.description == "new"

    def test_valid_fields_still_saved_when_one_is_stripped(self, target_user, regular_user):
        """When email is blocked, first_name and last_name should
        still be updated."""
        processor = GetOrCreateProcessor(target_user)

        with patch(
            "aap_gateway_api.resource_api.get_current_user",
            return_value=regular_user,
        ):
            processor.save(
                {
                    "email": "hijacked@example.com",
                    "first_name": "NewFirst",
                    "last_name": "NewLast",
                },
                is_new=False,
            )

        target_user.refresh_from_db()
        assert target_user.email == "original@example.com"
        assert target_user.first_name == "NewFirst"
        assert target_user.last_name == "NewLast"

    def test_serializer_exception_allows_update(self, target_user, superuser):
        """If the serializer raises an unexpected exception the
        update should still proceed (fail-open for robustness)."""
        processor = GetOrCreateProcessor(target_user)

        with (
            patch(
                "aap_gateway_api.resource_api.get_current_user",
                return_value=superuser,
            ),
            patch(
                "aap_gateway_api.resource_api._get_gateway_serializer_map",
                side_effect=RuntimeError("boom"),
            ),
        ):
            processor.save(
                {"first_name": "StillWorks"},
                is_new=False,
            )

        target_user.refresh_from_db()
        assert target_user.first_name == "StillWorks"
