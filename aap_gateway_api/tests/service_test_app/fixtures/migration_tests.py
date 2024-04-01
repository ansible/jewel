from service_test_app.models import Organization, Team, User


def setup():
    strickland = Organization.objects.create(name="Strickland Propane")
    tank_wipes = Team.objects.create(name="tank wipes", organization=strickland)
    a_managers = Team.objects.create(name="assistant managers", organization=strickland)
    drivers = Team.objects.create(name="drivers", organization=strickland)

    avengers = Organization.objects.create(name="The Avengers")
    real_h = Team.objects.create(name="Real Super Heroes", organization=avengers)
    normal_h = Team.objects.create(name="Normal people that are just kind of good at stuff", organization=avengers)

    org1 = Organization.objects.create(name="Org 1")
    org2 = Organization.objects.create(name="Org 2")
    org3 = Organization.objects.create(name="Org 3")

    org1_team = Team.objects.create(name="Team 1", organization=org1)
    org2_team = Team.objects.create(name="Team 1", organization=org2)
    org3_team = Team.objects.create(name="Team 1", organization=org3)

    u = User.objects.create(username="hank")
    u.organizations.set([strickland])
    u.organizations_administered.set([strickland])
    u.teams.set([a_managers])

    u = User.objects.create(username="mr_strickland")
    u.organizations.set([strickland])
    u.organizations_administered.set([strickland])

    u = User.objects.create(username="joe_jack")
    u.organizations.set([strickland])
    u.teams.set([drivers])
    u.teams_administered.set([drivers])

    u = User.objects.create(username="bobby")
    u.teams.set([tank_wipes])

    u = User.objects.create(username="t_stark")
    u.organizations.set([avengers])
    u.organizations_administered.set([avengers])
    u.teams.set([normal_h])
    u.teams_administered.set([normal_h])

    u = User.objects.create(username="cpt_murica")
    u.organizations.set([avengers, org1])
    u.organizations_administered.set([org1])
    u.teams.set([real_h])
    u.teams_administered.set([real_h])

    u = User.objects.create(username="point_break")
    u.teams.set([real_h, org1_team, org2_team, org3_team])

    u = User.objects.create(username="natasha")
    u.teams.set([normal_h])

    u = User.objects.create(username="hawkeye")
    u.teams.set([normal_h])
