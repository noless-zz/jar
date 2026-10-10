# Releasing the Android app to the family

Family phones run the **release** build, called "Jar". When a newer version is on
[GitHub Releases](https://github.com/noless-zz/jar/releases), the app shows **Jar X.Y.Z is available → Update**.
It also sends a notification once per version. Tapping Update downloads the APK and opens Android's installer.

Your Android Studio builds are the **dev** build ("Jar dev", package `com.noam.jar.dev`). The dev build
installs next to the family app and never replaces it.

## Publishing a version

1. Commit your changes.
2. In VS Code, open **More → Android: Publish release** and type a version higher than the last one, e.g. `0.4.0`.
   It writes the version to `android/VERSION`, commits and pushes. Changing that file on GitHub's website works too.
3. GitHub Actions builds and signs the APK (about 5 minutes) and attaches `jar-0.4.0.apk` to the release.
4. Phones pick it up on their next check (every 6 hours), or right away from **⋮ → Check for updates**.

Versions are `major.minor.patch`, each part 0-99. The version code is `major*10000 + minor*100 + patch` and must
only go up. Android refuses to install a lower one.

## First-time setup (once)

- **Signing key.** It lives in `data\secrets\jar-release.jks`, and its passwords are in
  `data\secrets\android-signing.properties`. Neither file ever goes to GitHub.
  **Back up the `data\secrets` folder** (OneDrive, USB, password manager). Without the key,
  updates can't install over the family's app, and everyone would have to uninstall and pair again.
- **GitHub secrets.** Open **More → Set GitHub release secrets**. It uses the GitHub CLI if you have it
  (`winget install GitHub.cli`, then `gh auth login`). Without the CLI it copies each of the 4 values to the clipboard
  and opens the GitHub secrets page for you to paste them.
- **git.** `winget install Git.Git`. Then run **More → Link this folder to GitHub** once.

## Installing on a new phone

On the phone, open https://github.com/noless-zz/jar/releases/latest and download the `.apk` from **Assets**.
Open it, allow "Install unknown apps" for the browser when asked, and install.
Then pair: dashboard → **Pair a phone** → pick the name.

## Moving from the old debug app

The earlier test app was a debug build signed with a different key. Android won't update it to the release build.
Uninstall it once, install the release, and pair again.
