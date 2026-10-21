
# GitHub to PyPI in 30 minutes

The PyPI is a godsend for Python users, placing most packages they need an easy `pip install` away.
The process of *putting* code on PyPI however has long been much more convoluted.

The good news is that since cerca 2020–2022, we have seen the result of massive standardization efforts on the Python packaging front.[^standardization] The consequence is that for simple projects, it is now possible to devise an almost completely portable procedure that will work for all of them.
The less good news is that with packaging tools still in a bit of flux, a lot of the information you find on the web may seem contradictory, and most of it makes the process more complicated than it now needs to be.

This little resource is my attempt at collating current recommendations, as of August 2023, into the simplest possible path to PyPI publication. It provides workflow files & guidelines that I can reuse across multiple projects. My hope is that they will also be useful to you, either as⁻is or as a starting point for your own packaging adventure.

This is **not** a tutorial on publishing to PyPI. That would be beside the point, since it would make this short document very much not short. Also, there are already multiple tutorials available, which are more likely to stay up to date than whatever I write here. My goal here is not for completeness, but maximum concision. If this is your first time using these tools, you will need to look up how they work separately.

On the other hand, if you just want to get your package on PyPI as quickly as possible and with minimum fuss, this is the resource for you. Just copy a few files into your repo, add the project to PyPI, and you should be good to go. 

[^standardization]: Those results of course are the outcome of mostly unnoticed work begun many years prior to 2020. Have a kind thought for all the people who have the vision and dedication to keep improving the Python ecosystem!

## Assumptions & tool choices

There are different ways to get a package on PyPI. This guidebook assumes or uses the following:

- [PyPA’s `build`](https://pypa-build.readthedocs.io/en/latest/)
    + This means that only [`pyproject.toml`](https://setuptools.pypa.io/en/latest/userguide/pyproject_config.html) projects are supported.
- Version numbers are automatically determined by [`setuptools-scm`](https://github.com/pypa/setuptools_scm), with [SemVer](https://semver.org/) tag names.
    + In particular, this means the `pyproject.toml` should not specify the version explicitely, but rather contain a line like `dynamic = ["version"]`.
- [Trusted publishing](https://docs.pypi.org/trusted-publishers/using-a-publisher/) to avoid the need for API tokens.
- GitHub, because it is currently the only Trusted Publisher.
- [GitHub Actions](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/)
    + Once properly configured, this allows publishing literally at the click of a button. (In contrast to e.g. `twine`, which requires issuing commands you probably forgot since the last time.)
- Separate GitHub workflows for building and publishing.
    + [pypi-publish](https://github.com/marketplace/actions/pypi-publish) action
    + Test builds with the `Build` workflow.
    + Once the build succeeds and you are confident in the result, trigger the `Publish` workflow.
      This reuses the `Build` as a [reusable workflow](https://docs.github.com/en/actions/sharing-automations/reusing-workflows), so if the build works on its own, it works here too.
    + Most new versions don’t require re-testing the build, so you can
      trigger the `Publish` workflow immediately and have everything done at once.
      

## Step-by-step instructions for publishing

### Create accounts

(Skip if you already have accounts on these services.)

- On [TestPyPI](https://test.pypi.org)
- On [PyPI](https://pypi.org/)

### Repo configuration

Do this with the GitHub web UI. (These are my personal preferences; adapt as desired.)

- Settings
    - General
        - Default branch
            - main
    - Rulesets
        - Add a *branch ruleset*
            - Name: "Protected main branch"
            - Targeting criteria: `main`
            - Rules:
                - ☑ Restrict deletions
        - Add a *tag ruleset*
            - Name: "Protected `v*` tags"
            - Bypass list: Repository admin
            - Target criterion (inclusion): `v*`
            - Rules:
                - ☑ Restrict creations
                - ☑ Restrict updates
                - ☑ Restrict deletions
                - ☑ Block force pushes
    - Environments
        - Create 2 environments
            - `release`
                - Wait timer: 15 minutes[^why-timer]
                    - Double check that the timer has been applied. You may need to click the text box and press Enter.
                - Deployment branches and tags: "Selected branches and tags"
                    - Add deployment branch or tag rule: Ref type "Branch", pattern `main`
                    - Add deployment branch or tag rule: Ref type "Tag", pattern `v*`
                      (needed because release events run on the tag, not on `main`)
            - `release-testpypi`

[^why-timer]: Once a package is published to PyPI, it cannot be replaced except by publishing a new version with a newer version number. The timer is intended to give you time to realize a mistake and cancel the `release` action before it runs.

### Add GitHub Actions

- Copy the three GitHub workflow files from this repo to your project repo under `.github/workflows/`
    + There are different ways to do this. A simple way is to just download the files from this repo (either by cloning or downloading the zip). A more sophisticated way is to clone the repo with [git-subrepo](https://github.com/ingydotnet/git-subrepo):

          mkdir .github
          git subrepo clone https://github.com/alcrene/publish-to-pypi .github/workflows

      The main advantages of using `git-subrepo` is that it allows you to update the workflows with `git subrepo pull`. You can also `git subrepo push` changes, if you use your own repository.

- Edit `.github/workflows/build.yml` as needed.
    + In particular, check that the Python version is appropriate.
    
#### Description of the workflows

- `build.yml`:
    + Will build the distribution files (runs `python3 -m build`)
    + Will run:
        + when called by one of the publish workflows;
        + when triggered manually from the *Actions* menu.

- `publish-on-pypi.yml`:
    + Will trigger a new build of the package (by calling `build.yml`).  
      If that succeeds, a 15-minute timer starts, after which
      the result of the build is automatically published to the official PyPI index
    + Permanent: Once a package is published with PyPI with a version number, no new packages can be published with the same number.
    + Runs within the environment `release`.
    + Will run:
        + when a new release (not marked as pre-release) is created with the GitHub UI;
        + when triggered manually from the *Actions* menu.

- `publish-on-testpypi.yml`:
    + Will trigger a new build of the package (by calling `build.yml`).  
      If that succeeds,
      the result of the build is automatically published to the test PyPI index
    + The test index can be used
        + to make sure the packaging pipeline works as it should;
        + to share pre-release with others to allow them to test them.
            + Packages on test PyPI are installed with `pip install -i https://test.pypi.org/simple/ <pkg name>`
    + Runs within the environment `release-testpypi`.
    + Will run:
        + when triggered manually from the *Actions* menu
                
### Prepare PyPI/TestPyPI

Actions are configured to use [*Trusted publishing*](https://docs.pypi.org/trusted-publishers/using-a-publisher/). This avoids the need to generate and store API tokens in the job file, and thus enables (almost) completely generic jobs. What we need to do however is tell PyPI / TestPyPI to expect our new package

From your PyPI user page:

* Publication
    + Add a new pending publisher
        - Project name: must match the `name` field in `pyproject.toml`
        - Workflow name: `publish-on-pypi.yml`
        - Environment name: `release`
    
If you intend to use TestPyPI, you need to repeat the procedure there

* Workflow name: `publish-on-testpypi.yml`
* Environment name: `release-testpypi`

### Publish a release candidate to TestPyPI

When you are ready to publish a new release, do the following:
(The procedure is the same for the first or subsequent releases.)

- Tag the latest commit with an RC version number: `v0.1.0-rc.1`
  + Make sure to use a [SemVer](https://semver.org/) so that build tools recognize the version number.
  + The GitHub actions will always build and publish the latest commit with a SemVer tag.
  + Versions prefixed with `v` is the most common standard, and some tools may expect it.
  + Separating numbers – like `-rc.1` – ensures that they order properly with versions like `-rc.11`.
  + `setuptools_scm` will parse the version from the tag name and produce a nice number for the package: `0.1.0-rc1`.
  
- Push the tag to GitHub

- Optionally, trigger the `build.yml` workflow manually to inspect the build output before publishing.

- Manually trigger the `Publish release on TestPyPI` workflow.
  + This builds the latest tagged commit and uploads it in one run.

- Test as needed.

### Publish a new official version on PyPI

- Tag the latest commit with plain version number: `v0.1.0`
  + Make sure to use a [SemVer](https://semver.org/) so that build tools recognize the version number.
  + This *must* be the latest commit with a SemVer tag.
  + This *may* be the same commit as the latest RC version (and probably should), so the commit will have both an RC version tag and a non-RC version tag.
  + Versions prefixed with `v` is the most common standard, and some tools may expect it.
  
- Push the tag to GitHub

- Make a new release with the GitHub UI (not marked as pre-release).
  This automatically triggers the `Publish release on PyPI` workflow, which builds the latest tagged commit and uploads it in one run.
  + Alternatively, trigger the `Publish release on PyPI` workflow manually.
  + This will wait 15 minutes before starting. If during this window you realize you forgot something, you may cancel the action from the Action menu.

- Your package is now on PyPI !

## Attribution

The GitHub actions are derived from examples from the [PyPI docs](https://docs.pypi.org/trusted-publishers/using-a-publisher/) (Apache-2.0) and the [PyPI publish GitHub Action](https://github.com/marketplace/actions/pypi-publish#usage) (BSD-3).
