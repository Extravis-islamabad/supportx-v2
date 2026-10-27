<#-- SupportX (WP-039 session 2, D-099): set-password e-mail for invitations and resets, in the
     tenant's brand from attributes SupportX sets before sending (escaped: HTML output). -->
<#assign kind = (user.attributes.sx_mail_kind)!"reset">
<#assign brandName = (user.attributes.sx_brand_name)!realmName>
<#assign brandLogo = (user.attributes.sx_brand_logo)!"">
<#assign brandColour = (user.attributes.sx_brand_colour)!"#7e40d1">
<#assign rtl = !(ltr!true)>
<#assign start = rtl?then("right", "left")>
<html lang="${locale.language}" dir="${rtl?then('rtl','ltr')}">
<body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,Helvetica,sans-serif;color:#262626;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:8px;">
<tr><td style="padding:20px 24px;text-align:${start};">
<#if brandLogo?has_content><img src="${brandLogo}" alt="${brandName}" height="40" style="display:block;height:40px;width:auto;border:0"><#else><span style="font-size:20px;font-weight:bold;">${brandName}</span></#if>
</td></tr>
<tr><td style="height:4px;background:${brandColour};"></td></tr>
<tr><td style="padding:24px;font-size:15px;line-height:1.6;text-align:${start};">
<p>${msg("supportx." + kind + ".intro", brandName)}</p>
<p style="margin:24px 0;"><a href="${link}" style="background:${brandColour};color:#ffffff;text-decoration:none;padding:12px 20px;border-radius:6px;display:inline-block;">${msg("supportx." + kind + ".button")}</a></p>
<p>${msg("supportx.expiry", linkExpirationFormatter(linkExpiration))}</p>
<p style="color:#595959;font-size:13px;">${msg("supportx." + kind + ".ignore")}</p>
</td></tr>
</table></td></tr></table>
</body>
</html>
