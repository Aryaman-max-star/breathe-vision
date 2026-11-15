# Confirmation email for the pilot form (EmailJS, free tier)

When someone submits "Request a pilot", the site sends them a thank-you email straight from the browser through EmailJS. No server and no secrets in the page (the EmailJS public key is meant to be public).

## 1. Account and email service (5 minutes)
1. Sign up at https://www.emailjs.com (free: 200 emails a month).
2. Email Services > Add New Service > Gmail (or Outlook). Sign in with the team inbox the email should come from. Note the **Service ID**.

## 2. Template
Email Templates > Create New Template, then set:

- **To Email:** `{{to_email}}`
- **From Name:** `BREATHE Vision`
- **Reply To:** your team inbox
- **Subject:** `Thank you, your interest has been registered`
- **Content:**

```
Hi {{to_name}},

Thank you, your interest has been registered.
Thanks for contributing to the future of innovation.

We have noted {{company}} ({{role}}) for the BREATHE Vision pilot and will be in touch soon.

Team Jugaadenberg
BREATHE Vision, built at Junction 2026
```

Save and note the **Template ID**.

## 3. Public key
Account > General > **Public Key**.

## 4. Paste into index.html
Near the bottom of `index.html`:

```js
window.EMAILJS={publicKey:'YOUR_PUBLIC_KEY',serviceId:'YOUR_SERVICE_ID',templateId:'YOUR_TEMPLATE_ID'};
```

Replace the three values. Until they are filled in, the form still shows the thank-you message on the page but sends no email.

## 5. Lock it down
In EmailJS > Account > Security, add your site domain to the allowed origins so nobody else can use your key.

Variables the page sends: `to_name`, `to_email`, `company`, `role`.
