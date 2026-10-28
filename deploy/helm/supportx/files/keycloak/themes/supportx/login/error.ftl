<#-- Keycloak's error page (base/login/error.ftl), with one SupportX change (QA WP-039 BUG-02):
     a link that no longer works (an invitation withdrawn or sent again, whose account is gone)
     ends here with Keycloak's "invalid user" text, which SupportX made the sign-in failure text
     (D-104). Real sign-in failures are shown on the sign-in form, never on this page, so here
     the link's own text is shown instead. -->
<#import "template.ftl" as layout>
<@layout.registrationLayout displayMessage=false; section>
    <#if section = "header">
        ${kcSanitize(msg("errorTitle"))?no_esc}
    <#elseif section = "form">
        <div id="kc-error-message">
            <#if message.summary == msg("invalidUserMessage")>
                <p class="instruction" id="supportx-link-invalid">${kcSanitize(msg("supportxLinkNoLongerValidMessage"))?no_esc}</p>
            <#else>
                <p class="instruction">${kcSanitize(message.summary)?no_esc}</p>
            </#if>
            <#if traceId??>
                <p class="instruction" id="traceId">${msg("traceIdSupportMessage", traceId)}</p>
            </#if>
            <#if skipLink??>
            <#else>
                <#if client?? && client.baseUrl?has_content>
                    <p><a id="backToApplication" href="${client.baseUrl}">${msg("backToApplication")}</a></p>
                </#if>
            </#if>
        </div>
    </#if>
</@layout.registrationLayout>
