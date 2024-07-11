from django.urls import reverse


def test_min_max_int_range_options(admin_api_client, register_preference):
    url = reverse('setting-section-list', kwargs={'category_slug': 'min_max_test'})

    register_preference(
        section="min_max_test",
        preference_name="test_preference_1",
        default=7,
        required=False,
        encrypted=False,
        preference_type="int_range",
        help_text="This is a test preference",
    )

    register_preference(
        section="min_max_test",
        preference_name="test_preference_2",
        default=7,
        required=False,
        encrypted=False,
        preference_type="int_range",
        help_text="This is a test preference",
        min_value=7,
        max_value=14,
    )

    response = admin_api_client.options(url)
    assert response.status_code == 200
    assert response.data.get('actions', {}).get('PUT', None) is not None, "PUT action should be available for superuser"
    assert response.data.get('actions', {}).get('PUT', {}).get('test_preference_1', {}).get('min_value', None) is None
    assert response.data.get('actions', {}).get('PUT', {}).get('test_preference_1', {}).get('max_value', None) is None
    assert response.data.get('actions', {}).get('PUT', {}).get('test_preference_2', {}).get('min_value', None) == 7
    assert response.data.get('actions', {}).get('PUT', {}).get('test_preference_2', {}).get('max_value', None) == 14
