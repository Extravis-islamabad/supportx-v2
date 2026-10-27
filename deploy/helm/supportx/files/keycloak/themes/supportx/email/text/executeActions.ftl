<#ftl output_format="plainText">
<#assign kind = (user.attributes.sx_mail_kind)!"reset">
<#assign brandName = (user.attributes.sx_brand_name)!realmName>
${msg("supportx." + kind + ".intro", brandName)}

${link}

${msg("supportx.expiry", linkExpirationFormatter(linkExpiration))}

${msg("supportx." + kind + ".ignore")}
