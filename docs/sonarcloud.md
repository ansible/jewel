# sonarcloud

We use sonarcloud to help perform analysis on the code and ensure a certain
level of code coverage and testing against PRs.

Making sonarcloud work against PRs to a private repository is slightly
nontrivial. The way way have it set up, is by having a workflow that listens
for the completion of the normal CI workflow, and then running sonar. This
avoids the problem where normally GHA workflows run in the context of the user
submitting the PR - who might not have access to repository secrets (including
the sonarcloud API token).

So upon completion of the CI workflow, the sonar-pr workflow kicks off, running
in the context of the upstream repository. Then sonarcloud will use the GitHub
API to inject itself as a check on the PR.

Generally this works well - however it makes it hard to see when changes to the
`sonar-project.properties` file breaks sonarcloud. And since sonar doesn't run
and inject itself into the PR in that case, the PR appears to be green.

## Debugging sonarcloud

When a change to `sonar-project.properties` breaks sonarcloud, it can be
a little annoying to debug. I have found the best way to debug it is to
run `sonar-scanner` locally.

The download for `sonar-scanner` can be found at the top of this page:
https://docs.sonarsource.com/sonarqube/9.9/analyzing-source-code/scanners/sonarscanner/

NOTE: The directory structure matters. You can unzip the zip file anywhere, but
the files have to stay together. You *cannot* for example just move
`bin/sonar-scanner` to `/usr/local/bin/`, this will not work. But you can add
the `bin` directory you unzipped, into your $PATH. For example:

```
[user@host sonar-scanner-5.0.1.3006-linux]$ export PATH=`pwd`/bin:$PATH
```

and then you can execute `sonar-scanner` from any directory.

Looking at the entrypoint for the official sonarcloud GHA action gives insight
into how the scanner runs normally. You can view that here:
https://github.com/SonarSource/sonarcloud-github-action/blob/master/entrypoint.sh

You will need a sonar token, which you can get by logging into sonarcloud,
clicking your avatar on the top right, going to My Account, and then clicking
the Security tab.

Once you have a token, set it as an environment variable, `SONAR_TOKEN`:

```
export SONAR_TOKEN=your_token_here
```

Finally you can run `sonar-scanner`:

```
sonar-scanner -Dsonar.projectBaseDir=. -Dsonar.host.url=https://sonarcloud.io
```

You can look for the errors and iterate as quickly as you like, and then commit
the fix. Most errors tend to be at the bottom of the output.
