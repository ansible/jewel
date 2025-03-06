from service_test_app.models import User


def setup():
    User.objects.create(username="bademailuser1", first_name="Badema", last_name="Iluser", email="bademailuser_at_somewhere_dot_com")
    User.objects.create(username="invaliduser", first_name="Inva", last_name="Liduser", email="invaliduser_at_somewhere_dot_com")
