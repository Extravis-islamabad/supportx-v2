# Connecting Microsoft 365 and Gmail mailboxes: registering your own app

For administrators of an organisation that runs SupportX. D-109 (2).

SupportX can read support mailboxes over IMAP (available now) or, for Microsoft 365 and Google
Workspace, through the Microsoft Graph and Gmail APIs (coming with WP-024 session 2). The APIs
need an OAuth app. **You register that app yourself, once per SupportX installation, in your
own Microsoft or Google admin console.** Your mail then goes straight from Microsoft or Google
to your SupportX. It never passes through an app or a server run by Extravis, which matters
most for on-premises and sovereign installations.

You need to do this only once per installation, not once per mailbox. One app can read every
support mailbox you allow it to read.

> The names of menus and buttons below are as Microsoft and Google showed them in October 2026.
> They rename things from time to time. If a step looks different, look for the same setting
> under its new name.

## Before you start

- **The redirect address of your SupportX.** Admin › Mail shows it when you add a Microsoft 365
  or Gmail mailbox, ready to copy. It is your console's address followed by
  `/api/v1/integrations/oauth/callback`.
- **Who does it.** Registering the app needs an administrator of your Microsoft Entra ID tenant
  (Application Administrator or higher) or of your Google Workspace (Super Admin). Giving
  consent for the whole organisation needs the same roles.
- **Internet access.** These APIs are on the internet. An air-gapped SupportX cannot use them:
  use IMAP to a mail server inside your network instead.

## Microsoft 365 (Microsoft Graph)

SupportX reads, marks and moves messages, so it needs `Mail.ReadWrite`. It never sends mail
through Graph: replies go out through your SupportX's outgoing mail settings.

### 1. Register the app

1. Sign in to the Microsoft Entra admin center (entra.microsoft.com).
2. Go to **Identity › Applications › App registrations** and choose **New registration**.
3. **Name:** for example "SupportX mail". People see this name when they review apps.
4. **Supported account types:** "Accounts in this organizational directory only" (single
   tenant).
5. **Redirect URI:** platform **Web**, with your SupportX's redirect address (see *Before you
   start*).
6. Choose **Register**. Copy the **Application (client) ID** and the **Directory (tenant) ID**
   from the overview page: SupportX asks for both.

### 2. Give it a credential

Prefer a certificate: it cannot be read back the way a secret can.

- **Certificate (recommended):** **Certificates & secrets › Certificates › Upload
  certificate**. Upload the public part of a certificate your organisation issues. SupportX
  keeps the private key sealed with its installation key ring.
- **Client secret:** **Certificates & secrets › Client secrets › New client secret**. Choose
  an expiry your policy allows, and copy the **Value** at once (it is shown only once). Put a
  reminder in your calendar: when it expires, SupportX shows the mailbox as failing with the
  reason, and mail waits on the server until you add a new secret.

### 3. Choose how far the app reaches

There are two models. Pick one.

**A. Application permission, limited to the support mailboxes (recommended).** SupportX reads
the mailboxes without anyone signing in, and only the mailboxes you name.

1. **API permissions › Add a permission › Microsoft Graph › Application permissions**, then
   choose **Mail.ReadWrite**.
2. Choose **Grant admin consent for <your organisation>**.
3. **Limit the app to the support mailboxes.** Without this step, an application permission
   reaches every mailbox in your organisation. In Exchange Online, use **RBAC for
   Applications**: put the support mailboxes in a management scope and assign the
   application the "Application Mail.ReadWrite" role for that scope only (Exchange Online
   PowerShell: `New-ManagementScope`, then `New-ManagementRoleAssignment` with `-App` and
   `-CustomResourceScope`). Older tenants may still use an application access policy
   (`New-ApplicationAccessPolicy` with a mail-enabled security group of the support
   mailboxes). Microsoft is replacing that with RBAC for Applications.
4. Check it: `Test-ServicePrincipalAuthorization` should allow a support mailbox and deny any
   other.

**B. Delegated permission, signed in as the mailbox.** For an organisation that does not allow
application permissions.

1. **API permissions › Add a permission › Microsoft Graph › Delegated permissions**, then
   choose **Mail.ReadWrite** and **offline_access** (so SupportX can stay connected).
2. Grant admin consent, or let the mailbox's owner consent when they connect it.
3. In SupportX, someone signs in **as the support mailbox's account** when connecting it. A
   shared mailbox has no password of its own, so use model A for shared mailboxes.

### 4. Connect the mailbox in SupportX

1. Admin › Mail › **Add a mailbox**, then choose Microsoft 365.
2. Enter the tenant ID, the client ID and the certificate or secret, and the mailbox's address.
3. Choose **Test**. A working connection says "The mailbox answered". A refusal shows the
   reason on the page.

## Google Workspace (Gmail API)

SupportX reads, labels and archives messages, so it needs the `gmail.modify` scope. It never
sends mail through Gmail and never deletes mail unless you choose that for the mailbox.

### 1. Create a project and turn on the Gmail API

1. Sign in to the Google Cloud console (console.cloud.google.com) with your Workspace admin
   account.
2. Create a project, for example "SupportX mail", inside your organisation.
3. **APIs & Services › Library**: find **Gmail API** and choose **Enable**.

### 2. Set up the consent screen

1. **APIs & Services › OAuth consent screen** (shown as **Google Auth Platform** in newer
   consoles).
2. **User type: Internal**. Only accounts of your Workspace can connect, and Google does not
   need to review the app.
3. App name, for example "SupportX mail", and a support e-mail address of your organisation.
4. **Scopes › Add or remove scopes**: add `https://www.googleapis.com/auth/gmail.modify`.

### 3. Create the OAuth client

1. **APIs & Services › Credentials › Create credentials › OAuth client ID**.
2. **Application type: Web application**.
3. **Authorized redirect URIs:** your SupportX's redirect address (see *Before you start*).
4. Choose **Create**. Copy the **Client ID** and the **Client secret**: SupportX asks for both.

### 4. Connect the mailbox in SupportX

1. Admin › Mail › **Add a mailbox**, then choose Gmail.
2. Enter the client ID and secret, then choose **Connect**. A Google sign-in opens: sign in
   **as the support mailbox's account** and allow access.
3. Choose **Test**.

A Google group's address (a "collaborative inbox") cannot be connected this way, because it
has no account to sign in as. Use a real account for the support address, or forward the
group to one.

**Domain-wide delegation** (a service account that can act as any user) also works, but it
reaches every mailbox in your Workspace. Use it only if your policy requires it, and limit the
delegation to the `gmail.modify` scope.

## Afterwards

- **Rotate credentials** before they expire. SupportX shows a failing mailbox with its reason,
  and mail waits on the server, never lost, until it can read again.
- **To remove access,** delete the client secret or certificate, or remove the app's consent
  (Microsoft: **Enterprise applications › <app> › Permissions**; Google: **Security › API
  controls › App access control**). Then remove the mailbox in Admin › Mail.
- **Audit:** every mailbox change in SupportX is in the audit log (Admin › Audit). Microsoft
  and Google keep their own sign-in and consent logs for the app.
