from rest_framework.serializers import JSONField


# For type annotation in SettingsPreferenceMetadata class, which is needed for the UI to determine which widget to use for preferences
class JSONListField(JSONField):
    pass
