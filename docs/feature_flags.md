### Feature Flags

AAP Gateway uses Django-Flags for feature flag management, enabling controlled rollout of functionality across AAP services. Feature flags support A/B testing and phased deployments. It is following our [Ansible Engineering Feature Flag Strategy](https://handbook.eng.ansible.com/proposals/0012-FeatureFlags#phase-2).

#### Configuration
Flags can be configured through:
- Settings-based configuration (current)
- Database-driven configuration (planned)
- Runtime conditions 

#### Conditions
AAP Gateway supports several condition types:
- `boolean`: Simple on/off switch
- `feature`: Allows flags to depend on other flags being enabled
- More conditions planned (date-based, user-based, etc.)

#### Usage Examples
In Django templates:
```python
{% load feature_flags %}
{% flag_enabled 'FEATURE_RBAC' as rbac_enabled %}
{% if rbac_enabled %}
  <!-- Content displayed only when RBAC feature is enabled -->
{% endif %}
```

In Python code (Django views):
```python
from flags.state import flag_enabled

def my_view(request):
    # Check if a feature is enabled
    if flag_enabled('FEATURE_RBAC', request=request):
        return HttpResponse("RBAC is enabled!")
    
    # Check feature with dependency
    if flag_enabled('FEATURE_POLICY_EVALUATOR', request=request):
        # This will only be true if both POLICY_EVALUATOR and its
        # dependency (RBAC) are enabled
        return HttpResponse("Policy Evaluator is enabled!")
        
    return HttpResponse("Features are disabled.")
```

#### Best Practices
- Remove feature flags once the functionality is generally available
- When using feature dependencies, consider the evaluation order
- Avoid circular dependencies between features

#### Admin Interface (Planned)
In the future, feature flags will be configurable through the Django admin interface. This will allow runtime toggling of flags without application restarts.

For more information about Django-Flags see [Django-Flags Docs](https://cfpb.github.io/django-flags/).