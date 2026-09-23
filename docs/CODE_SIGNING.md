# Code signing: Azure Artifact Signing

Releases of BrightLink Echo (formerly FTC Whisper) are signed in CI with
**Azure Artifact Signing**, Microsoft's code-signing service. Microsoft renamed
it from "Trusted Signing" in January 2026, so older guides use the old names.
Signing runs in `.github/workflows/build-release.yml`, under the company
**BRIGHTLINK (OS) LTD** (company number 17459281).

Facts below were checked against Microsoft Learn on 2026-09-17.

## Status: LIVE since 2026-09-23

Identity validation passed on 2026-09-23 and Part 2 was completed the same day.
**v1.6.88 is the first signed public release.** Both assets verify as

```
status: Valid  signer: CN=BRIGHTLINK (OS) LTD, O=BRIGHTLINK (OS) LTD, L=Syston, S=Leicester, C=GB
```

In place now: certificate profile `echopublic` on the `brightlinksigning`
account (North Europe, Public Trust, Active), app registration
`brightlink-echo-signing` holding **Artifact Signing Certificate Profile
Signer** at the signing-account scope, a federated credential `github-release`
on the `release` environment, and six repo variables including
`REQUIRE_SIGNING=true`. No client secret exists.

The federated credential uses the portal's **immutable-ID subject format**,
`repo:RJMURPHY0@<orgId>/BrightLink-Echo@<repoId>:environment:release`. Those
numeric IDs survive a repo rename, unlike the name-based form that the
2026-09-22 rename would have broken.

Parts 1 and 2 below are kept as the record of how it was set up, and as the
runbook if the certificate profile or app registration ever has to be rebuilt.
The one thing that must never change is the **certificate subject**: SmartScreen
reputation binds to it, so street address and postcode were deliberately left
out and the subject must stay exactly as above.

---

## What signing does, and what it does not

| | Unsigned | Signed |
|---|---|---|
| SmartScreen publisher | "Unknown publisher" | BRIGHTLINK (OS) LTD |
| Windows 11 Smart App Control | Blocks the app outright | Allowed |
| Antivirus false positives | More | Fewer |
| First-download SmartScreen prompt | Yes | **Still yes, for a while** |

A signed app still gets an "unrecognised app" prompt, showing the company name,
until its reputation builds. Microsoft says this "can take several weeks and
hundreds of clean installs"
([SmartScreen reputation](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation)).
EV certificates no longer skip this, and only Microsoft Store distribution
avoids it entirely.

Reputation belongs to the signing identity, which is the company. **Renaming
the app costs nothing. Changing the company on the certificate starts
reputation again.**

## Eligibility

- UK **organisations** qualify. Individual developers must be in the US or
  Canada, so this has to be the company.
- There is no minimum company age. A Microsoft employee confirmed this in
  August 2026
  ([Q&A](https://learn.microsoft.com/en-us/answers/questions/5977141/azure-artifact-signing-trusted-signing-is-a-us-llc)).
  Older pages that say three years are out of date.
- A **paid** subscription is required: pay-as-you-go works, but free and trial
  subscriptions are refused. Basic tier is $9.99/month and is not pro-rated.
- Identity validation takes **1 to 20 business days** and can only be done in
  the Azure portal.
- Signing resources can never move to another subscription or tenant, so
  create them under the company's own Microsoft account, not FTC Safety's.

---

## Part 1: account and identity validation (start first, it is the slow part)

Have ready:
- the company number (17459281)
- the website, `https://brightlink.io`
- **two** mailboxes on brightlink.io that accept outside email with links (the second can be an alias or group)
- a passport or photo driving licence
- the Microsoft Authenticator app on your phone
- a payment card

Also worth doing first:
- **Put the company details on brightlink.io:** registered name, company number, registered office, and "Registered in England and Wales". UK law requires this on a company website anyway, and Microsoft checks that the website belongs to the company.
- **Make the domain registration name the company:** Microsoft may ask for a domain invoice that names it.
- **Download the certificate of incorporation** from the company's Companies House page (Filing history). A newly incorporated company is thin in public records, so expect Microsoft to ask for it.

1. **Create the Azure account.** Open [Azure pay-as-you-go](https://azure.microsoft.com/en-gb/pricing/purchase-options/pay-as-you-go/) and click **Sign up** with your brightlink.io email.
2. **Register the signing service.** In [portal.azure.com](https://portal.azure.com):
   1. Search **Subscriptions** and open your subscription.
   2. Open **Resource providers** and search `Microsoft.CodeSigning`.
   3. Click **Register**. Status shows **Registered**.
3. **Create the signing account.**
   1. Search **Artifact Signing Accounts** and click **Create**.
   2. Resource group: **Create new**, `brightlink-signing`.
   3. Account name: for example `brightlinksigning` (3 to 24 letters or numbers, globally unique).
   4. Region: **North Europe**. There is no UK region; its endpoint is `https://neu.codesigning.azure.net`.
   5. Pricing: **Basic**, then **Review + Create**.
4. **Give yourself the verifier role.**
   1. In the new account, open **Access control (IAM)**, then **Add role assignment**.
   2. Choose **Artifact Signing Identity Verifier**, add yourself, then **Review + assign**.

   Without this role the next button stays greyed out.
5. **Submit the identity validation.**
   1. In the account, open **Identity validations**, then **Organization**, then **New Identity**, then **Public**.
   2. Organization Name: `BRIGHTLINK (OS) LTD`, exactly as on the register.
   3. Website url: `https://brightlink.io`.
   4. Primary and secondary email: both on brightlink.io.
   5. Business Identifier: `17459281`.
   6. Address: the registered office.
   7. First and last name: yours, exactly as on your ID.
   8. Click **Create**. Status shows **In Progress**.
6. **Verify the email and your ID.**
   1. Click Microsoft's verification email within **7 days**; the link expires and cannot be resent.
   2. When status shows **Action Required**, do the ID check. It runs through AU10TIX and Microsoft Authenticator on your phone.
7. **Wait** until status shows **Completed**. If documents are requested you get three upload attempts, and every document must be dated within the last 12 months.

## Part 2: connect it to GitHub (after "Completed", about 15 minutes)

8. **Certificate profile.**
   1. In the signing account, open **Certificate profiles**, then **Create**, then **Public Trust**.
   2. Name: `echopublic`.
   3. Verified CN and O: pick the completed validation, then click **Create**.
9. **App registration** (the identity GitHub signs as).
   1. Open [App registrations](https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade) and click **New registration**.
   2. Name it `brightlink-echo-signing` and click **Register**.
   3. From **Overview**, copy the **Application (client) ID** and the **Directory (tenant) ID**.
10. **Let GitHub log in without a password.**
    1. In the app registration, open **Certificates & secrets**, then **Federated credentials**, then **Add credential**.
    2. Scenario: **GitHub Actions deploying Azure resources**.
    3. Organization `RJMURPHY0`, Repository `BrightLink-Echo`, Entity type **Environment**, GitHub environment name `release`. The subject must read `repo:RJMURPHY0/BrightLink-Echo:environment:release`: GitHub signs with the repo's CURRENT name, so a credential made for the old `FTC_Whisper` name no longer matches and the login fails.
    4. Name `github-release`, then **Add**.
11. **Allow it to sign.**
    1. In the signing account, open **Access control (IAM)**, then **Add role assignment**.
    2. Choose **Artifact Signing Certificate Profile Signer**.
    3. Select members: `brightlink-echo-signing`, then **Review + assign**.
12. **Add five repo variables** at [Actions variables](https://github.com/RJMURPHY0/BrightLink-Echo/settings/variables/actions), each via **New repository variable**. None of them is secret: the login is keyless.

    | Variable | Value |
    |---|---|
    | `AZURE_CLIENT_ID` | Application (client) ID from step 9 |
    | `AZURE_TENANT_ID` | Directory (tenant) ID from step 9 |
    | `SIGNING_ENDPOINT` | `https://neu.codesigning.azure.net` |
    | `SIGNING_ACCOUNT` | the account name from step 3 |
    | `SIGNING_PROFILE` | the profile name from step 8 |

13. **Test without releasing.**
    1. Open the [release workflow](https://github.com/RJMURPHY0/BrightLink-Echo/actions/workflows/build-release.yml) and click **Run workflow**, leaving **publish** unticked.
    2. When it finishes, **Verify signature** should be green with signer `BRIGHTLINK (OS) LTD`, and the signed exe is attached to the run as an artifact.
14. **Lock it on:** add a repo variable `REQUIRE_SIGNING` = `true`. From then on, a build that cannot sign fails instead of publishing unsigned.

The `release` environment is created automatically on the first run. If you ever restrict its deployment branches, allow both `main` and tags matching `v*`, or tag re-cuts lose signing.

---

## How the build behaves

- **All five variables set:** the build logs in to Azure with GitHub OIDC (no client secret exists anywhere), signs `dist\FTC Whisper.exe`, and copies it to both release assets. A copy keeps the signature. Both copies are then verified.
- **None set:** the build is unsigned and the run shows an "Unsigned build" warning. With `REQUIRE_SIGNING=true` it fails instead.
- **Some set:** the build fails and names the missing variables.
- **Run workflow** is a dry run unless **publish** is ticked, so testing signing never touches the live release. To re-cut a failed version, push a tag or tick **publish**.

## Release assets

| Asset | For | Name |
|---|---|---|
| `BrightLink-Echo.exe` | New downloads: the README link and the CRM's download button | Follows the product name in `brand.py` |
| `FTC-Whisper.exe` | Every installed copy's auto-updater | **Frozen: never rename** |

Both come from the one signed build and have identical hashes.

## Verifying a signed exe

Right-click the exe, then **Properties**, then **Digital Signatures**. Or:

```powershell
Get-AuthenticodeSignature "BrightLink-Echo.exe" | Format-List Status, SignerCertificate
```

`Status` must be `Valid`.

## Notes

- **Certificates:** Artifact Signing certificates last three days, but the RFC 3161 timestamp (`http://timestamp.acs.microsoft.com`) keeps every signature valid after the certificate expires.
- **Validation expiry:** identity validation expires. Microsoft emails reminders from 60 days before. If it lapses, signing stops, and with `REQUIRE_SIGNING=true` so do releases.
- **If validation fails:** see the [Artifact Signing FAQ](https://learn.microsoft.com/en-us/azure/artifact-signing/faq). The fallback is an OV code-signing certificate from a commercial CA.
- **Full reference:** the [Artifact Signing quickstart](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart).
