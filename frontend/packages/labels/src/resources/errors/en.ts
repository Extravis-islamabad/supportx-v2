// errors labels (see ../README.md). English is the reference.
export const en = {
  'checklist_import_failure.not_text': 'The file is not a UTF-8 text (CSV) file.',
  'checklist_import_failure.too_large': 'The file is larger than 5 MB.',
  'checklist_import_failure.too_many_columns': 'A row has more than 40 columns.',
  'checklist_import_failure.too_many_rows': 'The file has more than 5,000 rows.',
  'checklist_import_reason.empty': 'Empty row',
  'checklist_import_reason.too_many_items': "Past the checklist's item limit",
  'checklist_import_reason.value_too_long': 'Longer than 500 characters',
  'errors.action_link_expired': 'This link has expired. Open the request in the app instead.',
  'errors.action_link_not_found': 'This link is not valid.',
  'errors.action_link_revoked': 'This is no longer needed: the request was decided or withdrawn.',
  'errors.action_link_sign_in_required': 'Sign in to approve or reject this request.',
  'errors.action_link_stale': 'The request changed since this link was sent. Open it in the app.',
  'errors.action_link_used': 'This link has already been used.',
  'errors.already_known_error': '{{display_id}} is already a known error.',
  'errors.already_on_version': 'This run is already on that version.',
  'errors.already_taken': '{{taken_by}} has just taken this. Reload to see it.',
  'errors.already_yours': 'It is already assigned to you.',
  'errors.announcement_not_found': 'This announcement does not exist or is not available to you.',
  'errors.api_key_allowlist_invalid':
    'Enter up to 20 valid addresses or networks, such as 10.0.0.0/8.',
  'errors.api_key_expired': 'This API key has expired.',
  'errors.api_key_expiry_past': 'The expiry date must be in the future.',
  'errors.api_key_expiry_required':
    'Choose an expiry date: your organisation does not allow keys that never expire.',
  'errors.api_key_expiry_too_far': 'A key can last at most one year.',
  'errors.api_key_invalid': 'This API key is not valid.',
  'errors.api_key_ip_refused': 'This API key may not be used from this address.',
  'errors.api_key_name_invalid': 'Enter a name of up to 100 characters.',
  'errors.api_key_not_allowed': 'API keys cannot be used here: sign in through the browser.',
  'errors.api_key_not_found': 'This API key does not exist or is not yours.',
  'errors.api_key_owner_inactive': 'The owner of this API key is no longer active.',
  'errors.api_key_owner_not_service':
    'Keys for someone else can only belong to a service identity.',
  'errors.api_key_revoked': 'This API key has been revoked.',
  'errors.api_key_scope_unknown': 'Choose at least one of the scopes offered.',
  'errors.api_keys_people_off': 'Your organisation does not let people make their own API keys.',
  'errors.api_keys_unavailable': 'API keys are not set up on this installation.',
  'errors.api_scope_missing': 'This API key does not have the scope {{scope}}.',
  'errors.approval_changed': 'This approval changed meanwhile. Open it again.',
  'errors.approval_closed': 'This approval is already decided or no longer needed.',
  'errors.approval_not_found': 'This approval was not found.',
  'errors.approval_pending': '{{display_id}} already waits for an approval.',
  'errors.approval_segregation': 'You cannot approve your own request.',
  'errors.archive_busy': 'You already have two downloads running. Try again in a minute.',
  'errors.archive_too_large': 'These files come to more than {{max_mb}} MB. Pick fewer files.',
  'errors.archive_too_many_files': 'You can download up to {{max}} files at once.',
  'errors.asset_acknowledgement_answered': 'You have already answered this one.',
  'errors.asset_acknowledgement_not_found':
    "That acknowledgement isn't yours, or no longer exists.",
  'errors.asset_already_disposed': 'This asset already has a disposal record.',
  'errors.asset_audit_closed': 'This audit is closed and can no longer change.',
  'errors.asset_audit_item_not_found': 'That item is not part of this audit.',
  'errors.asset_audit_not_auditor': 'Only the auditors named on this audit can mark its items.',
  'errors.asset_audit_not_draft': 'This audit has already started.',
  'errors.asset_audit_not_found': "This audit does not exist, or you can't see it.",
  'errors.asset_audit_not_running': 'This audit is not running: start it first.',
  'errors.asset_audit_scope_frozen':
    'The scope is fixed once an audit starts: only the name, description, end date and auditors can change.',
  'errors.asset_audit_too_large': 'This scope holds more than {{max}} assets: narrow it down.',
  'errors.asset_batch_not_found': 'That batch is not at this site.',
  'errors.asset_book_for_yourself': 'In the portal you can book only for yourself.',
  'errors.asset_booked': '{{asset}} is booked for part of that time.',
  'errors.asset_booking_not_found': 'This booking no longer exists.',
  'errors.asset_booking_not_open': 'This booking was already handed over or cancelled.',
  'errors.asset_booking_taken':
    'That time is already taken. The next free day starts {{next_free}}.',
  'errors.asset_bulk_empty': 'Choose at least one asset.',
  'errors.asset_bulk_job_not_found': 'This bulk change was not found.',
  'errors.asset_bulk_too_many': 'Choose at most {{max}} assets at once.',
  'errors.asset_consumable_batch_tracking_fixed':
    'Batch tracking is chosen when a consumable is added and cannot be switched later. Add the product again as a new consumable instead.',
  'errors.asset_consumable_exists': 'This product is already kept as a consumable.',
  'errors.asset_consumable_has_stock':
    'There are still {{quantity}} in stock. Allocate or adjust them to zero first.',
  'errors.asset_consumable_not_found': 'This consumable no longer exists.',
  'errors.asset_copy_limit': 'Make between 1 and {{max}} copies at once.',
  'errors.asset_cost_not_found': 'This cost line no longer exists.',
  'errors.asset_disposal_not_found': 'This asset has no disposal record.',
  'errors.asset_disposed_read_only':
    'This asset is disposed, so it is read-only. Changing it needs the permission to change disposed assets.',
  'errors.asset_field_not_allowed':
    "Through your ticket you can change only this asset's state, location, notes and fitted parts. Ask an asset manager for anything else.",
  'errors.asset_group_dynamic':
    "A dynamic group's members come from its filter; change the filter instead.",
  'errors.asset_group_name_taken': 'Another group already has this name.',
  'errors.asset_group_not_found': 'That group no longer exists.',
  'errors.asset_has_components':
    'It has fitted components ({{count}}): detach them or dispose of them too.',
  'errors.asset_import_exists': 'A record with this key already exists, and the import only adds.',
  'errors.asset_import_file_not_readable': 'Use a CSV file or an Excel workbook ({{xlsx}}).',
  'errors.asset_import_file_not_utf8': 'Save the CSV file as UTF-8 and try again.',
  'errors.asset_import_file_too_large': 'The file is larger than {{max_mb}} MB.',
  'errors.asset_import_file_unsafe':
    'The workbook unpacks to far more than its size, so it was not opened.',
  'errors.asset_import_match_invalid': 'This kind of file cannot be matched that way.',
  'errors.asset_import_no_match': 'No record matches this row, and the import only updates.',
  'errors.asset_import_not_checked': 'Only a checked file can be imported. Check it again.',
  'errors.asset_import_not_found': 'This import was not found.',
  'errors.asset_label_job_not_found': "These labels don't exist, or someone else asked for them.",
  'errors.asset_label_job_not_ready': 'The labels are not ready to download.',
  'errors.asset_label_print_not_found': 'That print is no longer in the label history.',
  'errors.asset_labels_failed': 'The labels could not be made. Try again.',
  'errors.asset_labels_too_large': 'The labels would make too large a file: print fewer at once.',
  'errors.asset_life_cycle_in_use':
    'Product types still use this life cycle ({{used}}). Move them to another one first.',
  'errors.asset_life_cycle_not_found': 'This life cycle does not exist.',
  'errors.asset_life_cycle_protected':
    "The default life cycle can't be deleted. Make another one the default first.",
  'errors.asset_limit_reached':
    "Every IT asset slot in your organisation's plan is in use. Dispose of an asset or ask your administrator to add more.",
  'errors.asset_link_exists': 'These two assets are already linked that way.',
  'errors.asset_link_not_found': 'That link no longer exists.',
  'errors.asset_loan_not_found': 'That loan is closed or no longer exists.',
  'errors.asset_merge_booked': '{{asset}} is booked ahead. Cancel the booking before merging.',
  'errors.asset_merge_nested': 'One of these assets is fitted to the other. Take it out first.',
  'errors.asset_merge_on_loan': '{{asset}} is on loan. Take it back before merging.',
  'errors.asset_merge_same': 'Choose two different assets.',
  'errors.asset_merge_site_not_managed':
    'You do not manage assets at both sites, so these cannot be merged.',
  'errors.asset_merged': 'This asset was merged into another one.',
  'errors.asset_move_not_allowed': "This asset can't move to that state from where it is now.",
  'errors.asset_move_not_allowed_through_ticket':
    'Retiring or disposing of an asset is not done through a ticket. Ask an asset manager.',
  'errors.asset_no_default_state':
    'There is no default state to move the asset to. Ask an admin to check the asset states.',
  'errors.asset_no_disposed_state':
    'There is no disposed state to move the asset to. Ask an admin to check the asset states.',
  'errors.asset_not_a_component':
    'Only a component that nobody holds can be fitted through your ticket. Ask an asset manager to give out a whole asset.',
  'errors.asset_not_bookable':
    '{{asset}} cannot be booked: only loanable assets that are not retired or disposed can be.',
  'errors.asset_not_found': "This asset no longer exists, or you can't see it.",
  'errors.asset_not_loanable': "{{asset}} can't be loaned: it isn't loanable, or isn't in stock.",
  'errors.asset_not_on_this_loan': "That asset isn't out on this loan.",
  'errors.asset_note_not_found': 'This note no longer exists.',
  'errors.asset_on_loan': '{{asset}} is already out on a loan.',
  'errors.asset_portal_booking_off': 'Your organisation does not take bookings in the portal.',
  'errors.asset_product_ambiguous': 'More than one product has this name.',
  'errors.asset_product_not_found': 'This product does not exist.',
  'errors.asset_product_type_has_children':
    'Other product types sit under this one ({{used}}). Move or delete them first.',
  'errors.asset_product_type_in_use': 'Products still use this product type ({{used}}).',
  'errors.asset_product_type_not_found': 'This product type does not exist.',
  'errors.asset_restore_merged':
    'This asset was merged into {{asset}}. Confirm to restore it on its own.',
  'errors.asset_site_not_managed': 'You can only add or move assets to the sites you manage.',
  'errors.asset_state_in_use':
    'Moves in life cycles still use this state ({{used}}). Remove them first.',
  'errors.asset_state_not_found': 'This asset state does not exist.',
  'errors.asset_state_protected':
    "This state is used by loans, disposal or as its category's default, so it can't be deleted.",
  'errors.asset_stock_not_found': 'That stock no longer exists.',
  'errors.asset_stock_ran_out': 'Stock ran out: someone else took the last of it.',
  'errors.asset_stock_rule_exists': 'There is already a minimum for this and this site.',
  'errors.asset_stock_rule_not_found': 'This minimum no longer exists.',
  'errors.asset_stock_short': 'Not enough in stock: only {{available}} available.',
  'errors.audit_archive_missing': 'The archive file is no longer in storage.',
  'errors.audit_archive_not_found': 'This archive does not exist.',
  'errors.audit_archive_not_ready': 'Only a verified archive can be restored.',
  'errors.audit_archive_not_restored': 'Restore this archive first to read its entries.',
  'errors.audit_archive_out_of_order':
    'Entries of this month were sealed out of order; ask support to check the audit log.',
  'errors.audit_archive_unsealed':
    'Some entries of this month are not sealed yet, so it cannot be archived.',
  'errors.audit_archive_unverified':
    'The archive did not pass verification when read back from storage.',
  'errors.audit_entry_not_found': 'This audit entry does not exist.',
  'errors.audit_export_not_found': 'This export does not exist.',
  'errors.audit_export_not_ready':
    'This export cannot be downloaded (not ready, failed or expired).',
  'errors.audit_export_too_large': 'Too many entries for one export. Choose a shorter time range.',
  'errors.auth_not_configured': 'Sign-in is not configured for this installation.',
  'errors.authentication_failed': 'The mail server refused the sign-in.',
  'errors.authorization_unavailable':
    'Permissions cannot be checked right now. Please try again shortly.',
  'errors.bad_request': 'The request could not be processed.',
  'errors.brand_colour_contrast':
    'This colour is hard to read: text on it falls below the WCAG AA contrast level. Use the suggested colour or choose a darker one.',
  'errors.branding_not_found': 'This brand was not found.',
  'errors.break_glass_admin_only': 'Only a tenant administrator can name emergency administrators.',
  'errors.break_glass_ip_exempt_needs_break_glass':
    'Only an emergency administrator can be exempt from the IP allow-lists.',
  'errors.break_glass_needs_admin':
    'Only a tenant administrator can be an emergency administrator.',
  'errors.break_glass_needs_mfa':
    'This emergency account needs two-step sign-in set up before it can be used.',
  'errors.break_glass_not_self':
    'Another administrator must name you as an emergency administrator.',
  'errors.bulk_job_not_found': 'This bulk change was not found.',
  'errors.calendar_in_use':
    'Sites or support groups still use this calendar. Give them another calendar first.',
  'errors.calendar_not_found': 'This calendar does not exist or was deleted.',
  'errors.cannot_deactivate_self': 'You cannot deactivate yourself.',
  'errors.cannot_publish': 'This announcement cannot be published yet.',
  'errors.cannot_stop_own_sign_in': 'You cannot stop your own sign-in.',
  'errors.catalog_item_in_use':
    'This item has requests, so it cannot be deleted. Retire it instead.',
  'errors.catalog_item_incomplete':
    'The item was not complete at its planned publish time, so it stayed a draft.',
  'errors.catalog_item_not_found': 'This catalog item does not exist or is not open to you.',
  'errors.category_not_found': 'This category does not exist.',
  'errors.certificate_invalid':
    'The certificate could not be read. Paste the PEM with its private key.',
  'errors.certificate_key_mismatch': 'The private key does not belong to this certificate.',
  'errors.certificate_not_valid_now': 'The certificate has expired or is not valid yet.',
  'errors.certificate_unreadable': 'The certificate cannot be read: paste it in PEM format.',
  'errors.certificate_wrong_host': 'The certificate does not name this domain.',
  'errors.change_source_not_found': 'The record this change was made for was not found.',
  'errors.change_window_blocked':
    'A freeze blocks this time. Choose another time, or someone allowed to may let it go ahead with a reason.',
  'errors.checklist_item_not_found': 'This checklist item is no longer there.',
  'errors.checklist_library_not_found':
    'This library checklist is no longer there or is no longer offered.',
  'errors.checklist_not_found': 'This checklist is no longer there.',
  'errors.client_id_invalid': "Enter the sync app's application (client) ID.",
  'errors.closure_rules': 'Some things are needed before this can be done.',
  'errors.command_in_flight':
    'This run is waiting on a step that would move to a different kind of step. Let it finish first.',
  'errors.conflict': 'Someone else changed this item. Reload to see the latest version.',
  'errors.console_requester_only': 'This account uses the requester portal, not the console.',
  'errors.contact_editing_off':
    'Your organisation does not let you change your contact details here. Ask your service desk.',
  'errors.conversation_entry_not_found': 'This reply or note no longer exists.',
  'errors.copy_reference': 'Copy reference',
  'errors.cost_rate_date_taken':
    'This person already has a rate from that moment. Change that one instead.',
  'errors.cost_rate_not_found': 'The rate was not found.',
  'errors.cost_rate_superseded':
    'A later rate is already in force, so this one can no longer change. Set a new rate instead.',
  'errors.csrf_failed': 'This request could not be verified. Please reload the page and try again.',
  'errors.currency_change_needs_confirmation':
    'Changing the base currency needs a confirmation: amounts already recorded stay in the old one.',
  'errors.custom_field_entity_not_found':
    'Custom fields are not available for this kind of record.',
  'errors.custom_field_in_use':
    'Records hold values in this field. Retire it to keep it on old records, or remove it: old values stay in the history.',
  'errors.custom_field_limit_reached':
    'This kind of record already has {{limit}} custom fields, the most allowed. Remove or reuse one first.',
  'errors.custom_field_not_found': 'This custom field does not exist (any more).',
  'errors.custom_field_used_by_rule':
    'Automation rules use this field ({{rules}}). Change or remove those rules first.',
  'errors.dashboard_not_editable':
    'Only its owner can change this dashboard. Copy it to make your own.',
  'errors.dashboard_not_found': 'This dashboard does not exist or is not shared with you.',
  'errors.database_not_configured':
    'The service is not fully configured yet. Please contact your administrator.',
  'errors.default_board_kept':
    'The default change advisory board cannot be removed. Changes that no other board reviews go to it.',
  'errors.default_site_required':
    'The default site cannot be removed. Make another site the default first.',
  'errors.delivery_not_failed': 'This reply has not failed, so there is nothing to resend.',
  'errors.department_not_found': 'This department no longer exists.',
  'errors.desk_limit_reached': 'Your licence allows no more desks.',
  'errors.directory_disabled': 'This directory is switched off. Switch it on to sync.',
  'errors.directory_group_invalid':
    'One of the directory groups is not valid. Choose it again from the list.',
  'errors.directory_groups_required': 'Choose at least one group to sync.',
  'errors.directory_name_taken': 'Another directory already has this name.',
  'errors.directory_not_found': 'The directory was not found.',
  'errors.directory_secret_missing':
    'No working client secret or certificate is stored. Enter it again.',
  'errors.directory_tenant_invalid': "Enter the directory's tenant ID or its primary domain.",
  'errors.directory_unavailable':
    'The directory did not answer or refused the sync app. Try again in a moment.',
  'errors.domain_address_not_allowed': 'The domain points to an address SupportX does not contact.',
  'errors.domain_check_failed': 'The domain answered, but not like this SupportX.',
  'errors.domain_invalid': 'Enter a domain name such as help.example.com.',
  'errors.domain_limit': 'You can add at most {{max}} domains.',
  'errors.domain_not_found': 'This domain was not found.',
  'errors.domain_not_reachable': 'The domain could not be reached.',
  'errors.domain_not_resolving': 'The domain has no DNS record yet.',
  'errors.domain_reserved':
    "Addresses under this installation's own domain are given automatically.",
  'errors.domain_taken': 'This domain is already used.',
  'errors.domain_wrong_answer':
    'The domain does not point to this SupportX yet: check its DNS record.',
  'errors.domains_not_configured': 'Custom domains are not set up on this installation.',
  'errors.downtime_not_found': 'This downtime window does not exist.',
  'errors.duplicate_move': 'The same move is listed twice from one status. Keep one.',
  'errors.entitlement_required': 'Your plan does not include this feature.',
  'errors.entitlement_required.detail': '{{feature}} is not part of your organisation’s plan.',
  'errors.entitlements_unavailable':
    'Licence information is temporarily unavailable. Please try again shortly.',
  'errors.field.above_maximum': 'Maximum is {{max}}.',
  'errors.field.address_not_allowed':
    "This server address can't be used. Use the mail server's public name.",
  'errors.field.already_linked': 'These records are already linked.',
  'errors.field.announcement_message_required': 'Write the message people will see.',
  'errors.field.api_key_allowlist_invalid':
    'Enter up to 20 valid addresses or networks, such as 10.0.0.0/8.',
  'errors.field.api_key_expiry_past': 'The expiry date must be in the future.',
  'errors.field.api_key_expiry_required':
    'Choose an expiry date: your organisation does not allow keys that never expire.',
  'errors.field.api_key_expiry_too_far': 'A key can last at most one year.',
  'errors.field.api_key_name_invalid': 'Enter a name of up to 100 characters.',
  'errors.field.api_key_owner_not_service':
    'Keys for someone else can only belong to a service identity.',
  'errors.field.api_key_scope_unknown': 'Choose at least one of the scopes offered.',
  'errors.field.approver_is_requester': 'You cannot approve your own request; name someone else.',
  'errors.field.approver_not_active': 'Choose an active person.',
  'errors.field.approver_not_eligible':
    'Someone named cannot approve this problem (inactive, or without the right).',
  'errors.field.asset_api_name_taken': 'Another product type has this API name.',
  'errors.field.asset_batch_expires_before_made': 'The expiry date is before the date it was made.',
  'errors.field.asset_batch_required': 'This consumable is tracked in batches: name the batch.',
  'errors.field.asset_booking_ends_before_start': 'The end must be after the start.',
  'errors.field.asset_booking_too_long': 'A booking can last at most {{days}} days.',
  'errors.field.asset_group_static': 'Only a dynamic group has a filter.',
  'errors.field.asset_holder_not_found':
    'Choose an active person, a department or an asset you can see.',
  'errors.field.asset_identifier_invalid':
    'Use letters, digits and - . / : # only, without spaces.',
  'errors.field.asset_life_cycle_code_taken': 'Another life cycle has this code.',
  'errors.field.asset_life_cycle_default_needed':
    'There must be a default life cycle. Make another one the default instead.',
  'errors.field.asset_life_cycle_not_found': 'Choose a life cycle from the list.',
  'errors.field.asset_link_to_itself': "An asset can't be linked to itself.",
  'errors.field.asset_move_duplicate':
    'This move is already in the list, or goes to the same state.',
  'errors.field.asset_nested_in_itself':
    "An asset can't be fitted to itself or to one of its own parts.",
  'errors.field.asset_not_batch_tracked': 'This consumable is not tracked in batches.',
  'errors.field.asset_not_found': 'This asset does not exist or you may not see it.',
  'errors.field.asset_overdue_state_unreachable':
    'No life cycle of these product types moves an asset to this state. Choose one it can reach.',
  'errors.field.asset_product_not_consumable': 'Choose a product of a consumable type.',
  'errors.field.asset_product_not_found': 'This product no longer exists.',
  'errors.field.asset_product_type_cycle':
    "A product type can't sit under itself or one of its own types.",
  'errors.field.asset_product_type_inherited': 'This comes from the parent type. Change it there.',
  'errors.field.asset_product_type_not_found': 'Choose a product type from the list.',
  'errors.field.asset_product_type_too_deep': 'The tree can be at most {{max}} levels deep.',
  'errors.field.asset_quantity_positive': 'Enter a quantity above zero.',
  'errors.field.asset_salvage_above_cost':
    "The salvage value can't be more than what the asset cost.",
  'errors.field.asset_serial_number_taken': 'Asset {{asset}} already has this serial number.',
  'errors.field.asset_state_code_taken': 'Another state has this code.',
  'errors.field.asset_state_default_needed':
    'Each category needs a default state. Make another state the default instead.',
  'errors.field.asset_state_not_found': 'Choose states from the list.',
  'errors.field.asset_state_system':
    'Loans and disposal rely on this state, so its category stays.',
  'errors.field.asset_stock_rule_target': 'Choose either a product type or a product.',
  'errors.field.asset_tag_pattern_invalid':
    'Use the counter {n} once, with some text around it, e.g. AST-{n}.',
  'errors.field.asset_tag_taken': 'Asset {{asset}} already has this tag.',
  'errors.field.asset_type_not_consumable': 'Choose a consumable product type.',
  'errors.field.auto_close_needs_notifications':
    'Auto-close needs requester notifications: no channel can tell requesters of a resolution yet.',
  'errors.field.before_publish': 'Retiring must come after publishing.',
  'errors.field.before_start': 'The end cannot be before the start.',
  'errors.field.below_minimum': 'Minimum is {{min}}.',
  'errors.field.board_not_found': 'This advisory board does not exist.',
  'errors.field.brand_image_svg':
    'SVG images are not accepted: they can contain scripts. Use a PNG, JPEG, WebP or ICO file.',
  'errors.field.brand_image_too_large': 'This image is too large: at most 5 MB and 25 megapixels.',
  'errors.field.brand_image_too_small': 'This image is too small: at least 16 pixels on each side.',
  'errors.field.brand_image_unreadable':
    'This image cannot be read. Use a PNG, JPEG, WebP or ICO file.',
  'errors.field.bucket_not_allowed': 'Only date fields can be grouped by day, week or month.',
  'errors.field.bucket_required':
    'Choose how to group the dates: by day, week, month, quarter, year or age.',
  'errors.field.builtin_type_names': 'A built-in type keeps its names.',
  'errors.field.calendar_not_found': 'Choose a calendar from the list.',
  'errors.field.cannot_link_itself': 'A record cannot be linked to itself.',
  'errors.field.cannot_merge_itself': 'A problem cannot be merged into itself.',
  'errors.field.cannot_see_record': 'This person cannot see this record, so they cannot follow it.',
  'errors.field.catalog_item_not_found': 'Choose an item from the catalog that is open to you.',
  'errors.field.catalog_too_deep': 'Catalog categories have at most four levels.',
  'errors.field.category_disabled': 'This category is no longer in use.',
  'errors.field.category_loop':
    'A category cannot sit inside itself or one of its own subcategories.',
  'errors.field.category_not_found': 'This category does not exist.',
  'errors.field.certificate_key_mismatch': 'The private key does not belong to this certificate.',
  'errors.field.certificate_not_valid_now': 'The certificate has expired or is not valid yet.',
  'errors.field.certificate_unreadable': 'The certificate cannot be read: paste it in PEM format.',
  'errors.field.certificate_wrong_host': 'The certificate does not name this domain.',
  'errors.field.chair_inactive': 'Choose an active person as the chair.',
  'errors.field.change_in_other_release': 'This change is already in the open release {{release}}.',
  'errors.field.change_would_loop':
    'A change cannot be part of itself, directly or through others.',
  'errors.field.channel_reserved':
    'Only phone or walk-up can be chosen; other channels are set automatically.',
  'errors.field.choices_required': 'Add at least one choice.',
  'errors.field.code_taken': 'Another one already uses this code.',
  'errors.field.comment_required': 'Add a comment: this item requires one.',
  'errors.field.condition_not_supported': 'Rules are not available for this permission yet.',
  'errors.field.conflict_blocks':
    'A blocking conflict cannot be acknowledged. Choose another time, or someone allowed to may let it go ahead with a reason.',
  'errors.field.conflict_not_found':
    'This conflict is no longer there. The list shows the conflicts now.',
  'errors.field.country_invalid': 'Choose a country from the list.',
  'errors.field.currency_unknown': 'Choose a currency from the list.',
  'errors.field.dashboard_not_shared': "Only a built-in or shared dashboard can be a role's home.",
  'errors.field.date_format_unknown': 'Choose a date format from the list.',
  'errors.field.date_in_future': 'Choose today or an earlier date.',
  'errors.field.date_in_past': 'Choose a time later than now.',
  'errors.field.default_cannot_be_disabled':
    'The default template cannot be turned off. Make another template the default first.',
  'errors.field.default_cannot_be_inactive': 'The default cannot be made inactive.',
  'errors.field.default_cannot_be_removed':
    'The default rule cannot be removed. Switch it off instead.',
  'errors.field.default_language_not_offered':
    'The default language must be one of the languages offered.',
  'errors.field.default_required':
    'There is always a default template. Make another template the default instead.',
  'errors.field.department_not_found': 'Choose an active department.',
  'errors.field.dependency_loop': 'A task cannot wait for itself, directly or through other tasks.',
  'errors.field.desk_not_found': 'Choose an active desk.',
  'errors.field.dimension_not_groupable':
    'Fields with several choices cannot be used for grouping yet.',
  'errors.field.disabled_cannot_be_default': 'Turn this template on before making it the default.',
  'errors.field.domain_invalid': 'Enter a domain name such as help.example.com.',
  'errors.field.domain_reserved':
    "Addresses under this installation's own domain are given automatically.",
  'errors.field.due_in_past': 'Choose a moment in the future.',
  'errors.field.duplicate': 'This is already used.',
  'errors.field.duplicate_column': 'Each column can be listed once.',
  'errors.field.duplicate_dimension': 'This grouping is already used.',
  'errors.field.duplicate_measure': 'Each measure can be used once.',
  'errors.field.duplicate_name': 'This name is already used.',
  'errors.field.duplicate_permission': 'This permission is listed twice.',
  'errors.field.duplicate_sort_field': 'Each field can be used only once in the sort.',
  'errors.field.duplicate_value': 'This is listed more than once.',
  'errors.field.duration_mismatch': 'The duration does not match the start and end times.',
  'errors.field.email_invalid': 'Enter an e-mail address like name@example.com.',
  'errors.field.email_not_valid': 'Enter an email address, such as name@example.com.',
  'errors.field.email_required_for_sign_in':
    'An email address is needed to sign in. Add one, or make this person a contact.',
  'errors.field.email_taken': 'Another person already uses this email address.',
  'errors.field.employee_id_taken': 'Another person already has this employee ID.',
  'errors.field.end_before_start': 'The end date is before the start date.',
  'errors.field.end_or_duration_required': 'Enter an end time or a duration.',
  'errors.field.english_label_required': 'An English name is required.',
  'errors.field.english_text_required':
    'Add the English text: it is shown wherever no translation exists.',
  'errors.field.exception_range_order': 'The last day must be on or after the first day.',
  'errors.field.exception_range_too_long': 'Special hours can cover at most one year.',
  'errors.field.exception_ranges_overlap':
    'These dates overlap other special hours of this calendar. Change the dates or edit the other range.',
  'errors.field.expiry_before_review': 'The expiry date must be after the review date.',
  'errors.field.fallback_fixed': 'The default policy always applies and has no conditions.',
  'errors.field.field_always_required': 'Subject and requester are always shown and required.',
  'errors.field.field_locked': 'A form rule locks this field, so it cannot be changed here.',
  'errors.field.field_not_settable': 'A rule cannot set this field.',
  'errors.field.field_retired': 'This field is retired and takes no new values.',
  'errors.field.field_set_twice': 'This field is already set by another action of the rule.',
  'errors.field.fill_needs_see': 'Requesters can only fill in a field they can see.',
  'errors.field.filter_too_deep': 'The filter has too many nested groups.',
  'errors.field.filter_too_large': 'The filter is too large.',
  'errors.field.fixed_calendar_required': 'Choose the calendar to use.',
  'errors.field.fixed_calendar_unused':
    'A calendar is only chosen when the source is a fixed calendar.',
  'errors.field.flow_not_available': 'This kind of record has no created-vs-resolved report.',
  'errors.field.flow_without_groupings': 'A created-vs-resolved report has no groupings.',
  'errors.field.fulfiller_required': 'Assign someone to fulfil this request first.',
  'errors.field.full_sla_off':
    'Problems have target dates only. Switch on full SLAs for problems to add response targets.',
  'errors.field.group_dashboard_shared':
    "A group's dashboard can't also be shared with everyone. Take it out of the group first.",
  'errors.field.group_not_found': 'This group does not exist.',
  'errors.field.group_not_yours': 'You are not a member of this group.',
  'errors.field.group_required': 'Choose which of your groups takes it.',
  'errors.field.half_day_single_date': 'A morning or afternoon off is one day only.',
  'errors.field.hidden_cannot_be_required':
    'A hidden field cannot be required: nobody could fill it in.',
  'errors.field.hidden_required_needs_default':
    'A hidden required field needs a starting value, or nobody could fill it in.',
  'errors.field.holiday_list_not_found': 'Choose holiday lists from the list.',
  'errors.field.holiday_range_order': 'The last day must be on or after the first day.',
  'errors.field.holiday_range_too_long': 'A holiday can be at most one year long.',
  'errors.field.host_name_invalid': 'Enter server names only, such as mx.google.com.',
  'errors.field.ical_invalid': 'This is not an iCalendar (.ics) file.',
  'errors.field.ical_not_utf8': 'The file is not a text calendar file (UTF-8).',
  'errors.field.ical_too_large': 'The file is larger than 1 MB.',
  'errors.field.ical_too_many_lines': 'The file has more than 20,000 lines.',
  'errors.field.invalid_choice': 'This is not one of the allowed values.',
  'errors.field.invalid_code': 'Use letters, digits, dots, dashes or underscores (up to 50).',
  'errors.field.invalid_colour': 'Choose a colour such as #1677ff.',
  'errors.field.invalid_currency': 'Use a three-letter currency code, such as USD or SAR.',
  'errors.field.invalid_date': 'Enter a date.',
  'errors.field.invalid_email': 'These addresses are not valid: {{addresses}}',
  'errors.field.invalid_group': 'A group needs at least one condition.',
  'errors.field.invalid_json': 'The filter is not valid.',
  'errors.field.invalid_key': 'Give the field a name with at least two letters or digits.',
  'errors.field.invalid_language':
    'Names can be given in English, Arabic and Urdu, up to 200 characters each.',
  'errors.field.invalid_node': 'This part of the filter is not a condition or a group.',
  'errors.field.invalid_number': 'Enter a number.',
  'errors.field.invalid_pattern': 'This pattern is not a valid regular expression.',
  'errors.field.invalid_phone': 'Enter a phone number: digits, spaces, +, - and brackets.',
  'errors.field.invalid_prefix': 'Use 2 to 6 capital letters.',
  'errors.field.invalid_range': 'The start of the range is after its end.',
  'errors.field.invalid_sort': 'Choose between one and three sort fields.',
  'errors.field.invalid_tag': 'Tags may use letters, digits, spaces, dots and dashes (up to 40).',
  'errors.field.invalid_text': 'Enter text.',
  'errors.field.invalid_value': 'This value is not valid for the field.',
  'errors.field.invalid_website': 'Enter a web address starting with http:// or https://.',
  'errors.field.invitation_days_out_of_range': 'Use between {{min}} and {{max}} days.',
  'errors.field.ip_allow_everything':
    '“{{entry}}” would allow every address. Leave the list empty to allow everyone.',
  'errors.field.ip_allow_invalid':
    '“{{entry}}” is not an address or range. Use a form like 192.0.2.0/24 or 2001:db8::/32.',
  'errors.field.ip_allow_locks_you_out':
    'This list would shut you out: your address {{address}} is not in it. Add it, or a range that holds it.',
  'errors.field.ip_allow_too_many': 'Use at most {{max}} entries.',
  'errors.field.kb_vote_comment_too_long': 'Keep the comment to 1,000 characters.',
  'errors.field.kb_vote_reason_for_no_only': 'A reason goes with "No" only.',
  'errors.field.kb_vote_reason_unknown': 'Choose one of the reasons offered.',
  'errors.field.key_cannot_change': "The field's API name cannot change.",
  'errors.field.languages_invalid': 'English is always offered; choose any of Arabic and Urdu too.',
  'errors.field.last_value': 'At least one value must stay in use.',
  'errors.field.level_does_nothing':
    'This level tells no one and does nothing. Add recipients or an action.',
  'errors.field.level_too_many_actions': 'At most {{max}} actions per level.',
  'errors.field.level_too_many_recipients': 'At most {{max}} recipients per level.',
  'errors.field.levels_same_moment': 'Two levels run at the same moment. Give each its own time.',
  'errors.field.limited_template_for_requesters':
    'A template for requesters is offered to everyone: it cannot be limited to groups.',
  'errors.field.list_too_long': 'Too many values in this list.',
  'errors.field.logo_required': 'Upload a logo first.',
  'errors.field.longer_than_a_month': 'A monthly window can be at most 28 days long.',
  'errors.field.longer_than_a_week': 'A weekly window can last a week at most.',
  'errors.field.mailbox_address_invalid': "Enter the mailbox's e-mail address.",
  'errors.field.mailbox_auth_model_unsupported': 'Not available for this kind of mailbox.',
  'errors.field.mailbox_provider_results_graph_only':
    "Only a Microsoft 365 mailbox can trust Microsoft's own result.",
  'errors.field.managed_by_directory': 'Your directory keeps this field. Change it there.',
  'errors.field.manager_loop':
    'This person already manages that manager (directly or through others).',
  'errors.field.matrix_incomplete': 'Every impact and urgency pair needs a priority.',
  'errors.field.measure_not_available': 'This measure is not available yet.',
  'errors.field.message_required': 'Write the message in English at least.',
  'errors.field.mfa_grace_out_of_range': 'Use between {{min}} and {{max}} days.',
  'errors.field.mfa_mode_invalid': 'Choose off, optional or required.',
  'errors.field.month_out_of_range': 'Choose a month from the list.',
  'errors.field.move_articles_first': 'This topic still holds articles. Choose where they go.',
  'errors.field.must_be_future': 'Choose a time in the future.',
  'errors.field.my_groups_in_records':
    'A list cannot use "my groups". Use a chart, or choose groups.',
  'errors.field.name_needs_letters': 'Use at least one letter or digit in the name.',
  'errors.field.name_required': 'Enter a name.',
  'errors.field.name_taken': 'Another one already uses this name.',
  'errors.field.needs_collapsible': 'Only a collapsible section can start closed.',
  'errors.field.needs_scheduled_start': 'A reminder before the start needs a scheduled start.',
  'errors.field.no_default_allowed': 'This field cannot have a starting value.',
  'errors.field.not_a_field': 'This field does not exist for this type.',
  'errors.field.not_a_form_field': 'This field is not on the form.',
  'errors.field.not_a_technician': 'Only a technician who works on problems can investigate one.',
  'errors.field.not_allowed': 'This is not allowed together with the other values.',
  'errors.field.not_allowed_for_notes': 'Notes have no recipients.',
  'errors.field.not_eligible': 'This person or group may not hold this role.',
  'errors.field.not_for_personal': 'A personal template is yours only, so it has no groups.',
  'errors.field.not_for_replies': 'Only resolution templates have categories.',
  'errors.field.not_for_this_status': 'This setting is only for statuses that wait on someone.',
  'errors.field.not_found': 'This no longer exists.',
  'errors.field.not_in_past': 'This time must be in the past.',
  'errors.field.note_too_long': 'The note can be at most {{max}} characters.',
  'errors.field.number_already_used': 'That number is already used. Choose {{minimum}} or higher.',
  'errors.field.oauth_certificate_invalid':
    'Paste the certificate and its RSA private key, both as PEM.',
  'errors.field.offset_too_large':
    'A level can be at most 30 business days from its starting point.',
  'errors.field.one_day_required': 'Choose one day of the week.',
  'errors.field.operator_not_allowed': 'This comparison cannot be used with this field.',
  'errors.field.order_incomplete':
    'The list changed while you were reordering. Reload and try again.',
  'errors.field.order_must_list_every_value': 'The list changed meanwhile. Reload and try again.',
  'errors.field.out_of_range': 'This number is outside the allowed range.',
  'errors.field.owner_not_allowed': 'This person may not manage announcements, so cannot own one.',
  'errors.field.parent_loop': 'This would make it its own parent.',
  'errors.field.password_policy_out_of_range': 'Use between {{min}} and {{max}}.',
  'errors.field.pattern_mismatch': 'This value does not have the expected format.',
  'errors.field.pattern_too_complex':
    'This pattern repeats a group that itself repeats, which could make saving very slow. Simplify it, for example [A-Z]+ instead of ([A-Z]+)+.',
  'errors.field.period_time_invalid': 'Enter times as HH:MM, from 00:00 to 24:00.',
  'errors.field.period_weekday_invalid': 'Choose a day of the week.',
  'errors.field.periods_overlap':
    "Working periods overlap. A night period must also end before the next morning's period starts.",
  'errors.field.person_in_no_group':
    'This person is in no support group, so nothing can be assigned to them.',
  'errors.field.person_not_in_group': 'This person is not a member of the chosen group.',
  'errors.field.phone_not_valid': 'Enter a phone number: digits, spaces, +, - and brackets.',
  'errors.field.plain_connection_refused':
    'A connection without encryption is refused unless you allow it.',
  'errors.field.port_not_allowed': 'Use a mail port: 993 (TLS) or 143.',
  'errors.field.private_key_unreadable':
    'The private key cannot be read: paste it unencrypted in PEM format.',
  'errors.field.range_end_before_start': 'The end must be after the start.',
  'errors.field.read_category_unknown': 'This kind of read cannot be logged.',
  'errors.field.read_only': 'This field cannot be changed here.',
  'errors.field.read_only_in_stage': 'This field cannot be changed in the current stage.',
  'errors.field.reason_required': 'Give a reason.',
  'errors.field.reassign_group_required':
    'This person is in several groups: choose the one the record moves to.',
  'errors.field.recipient_shape': 'Choose the person or group for this recipient.',
  'errors.field.recipients_required': 'Choose at least one person or group.',
  'errors.field.record_not_found': 'No record you can see has this ID.',
  'errors.field.replies_are_public':
    'Replies go to people outside the team, so they are always public.',
  'errors.field.report_not_found': 'This report does not exist or is not shared with you.',
  'errors.field.requester_always_needed':
    'Subject and requester are always seen and filled in by requesters.',
  'errors.field.requester_audience_empty':
    'Choose at least one requester group, site or department.',
  'errors.field.requester_only': "Only the requester's confirmation sets this code.",
  'errors.field.required': 'This field is required.',
  'errors.field.required_for_known_error':
    'Write a workaround or a root cause before marking a known error.',
  'errors.field.required_for_move': 'Fill this in before the move.',
  'errors.field.required_to_close': 'Needed before closing.',
  'errors.field.required_to_confirm_cause': 'Write the root cause before confirming it.',
  'errors.field.required_to_leave_stage': 'Fill this in before leaving this stage.',
  'errors.field.required_to_resolve': 'Needed before resolving.',
  'errors.field.review_date_past': 'Choose today or a later date.',
  'errors.field.review_required_to_close': "Complete the release's review before closing it.",
  'errors.field.role_disabled': 'This role is retired: it cannot be given to anyone new.',
  'errors.field.role_held_by_record':
    "This role follows the record's own field. Change it in the details panel.",
  'errors.field.rule_too_deep': 'Conditions nest at most three levels.',
  'errors.field.same_folder': 'Choose a different folder for its reports.',
  'errors.field.schedule_never_runs': 'With these dates the schedule would never run.',
  'errors.field.scope_not_allowed': 'This scope is not available for this permission.',
  'errors.field.session_absolute_out_of_range':
    'Use at least the idle timeout and at most {{max}} hours.',
  'errors.field.session_idle_out_of_range': 'Use between {{min}} and {{max}} minutes.',
  'errors.field.site_inactive': 'This site is inactive. Choose an active site.',
  'errors.field.site_not_found': 'This site does not exist.',
  'errors.field.sso_certificate_expired':
    'The certificate has expired. Ask the identity provider for a current one.',
  'errors.field.sso_certificate_missing': 'The metadata has no signing certificate.',
  'errors.field.sso_certificate_required': "Paste the identity provider's signing certificate.",
  'errors.field.sso_certificate_unreadable':
    'The certificate cannot be read: paste it in PEM format.',
  'errors.field.sso_client_id_required': 'Enter the client ID.',
  'errors.field.sso_client_rejected': 'The identity provider refused this client ID and secret.',
  'errors.field.sso_client_secret_required': 'Enter the client secret.',
  'errors.field.sso_discovery_invalid':
    'This address does not answer like an OpenID Connect issuer.',
  'errors.field.sso_discovery_unreachable': 'SupportX cannot reach this issuer. Check the address.',
  // WP-039 identity: Admin > Sign-in and security
  'errors.field.sso_domain_in_use':
    '{{domain}} is already used by another single sign-on set-up of yours.',
  'errors.field.sso_domain_invalid': '{{domain}} is not a domain name, such as example.com.',
  'errors.field.sso_domain_public':
    '{{domain}} is a public mail service and cannot be used for single sign-on.',
  'errors.field.sso_domain_required': 'Add at least one email domain.',
  'errors.field.sso_domain_taken': 'One of these domains is already used by another organisation.',
  'errors.field.sso_domain_unverified':
    'Prove that your organisation owns {{domain}} before single sign-on can use it.',
  'errors.field.sso_domains_too_many': 'Use at most {{max}} domains.',
  'errors.field.sso_issuer_mismatch':
    'The issuer this address names is a different one. Use the exact issuer address.',
  'errors.field.sso_issuer_required': 'Enter the issuer address.',
  'errors.field.sso_metadata_required':
    'Upload the metadata, give its address, or fill in the sign-in address.',
  'errors.field.sso_metadata_unreachable': 'SupportX cannot fetch the metadata from this address.',
  'errors.field.sso_metadata_unreadable': 'This file is not readable SAML metadata.',
  'errors.field.sso_name_length': 'Use 1 to {{max}} characters.',
  'errors.field.sso_protocol_fixed': 'A set-up keeps its protocol. Add a new one instead.',
  'errors.field.sso_sign_in_url_missing': 'The metadata has no sign-in address.',
  'errors.field.sso_url_invalid': 'Enter a full address that starts with https://.',
  'errors.field.system_calendar_fixed':
    'Around the clock always counts every hour. Only its name can change.',
  'errors.field.target_amount_invalid': 'Enter a whole number from 1 to 100,000.',
  'errors.field.target_duplicate': 'This target is already set for this priority.',
  'errors.field.technician_audience_empty': 'Choose all technicians or at least one group.',
  'errors.field.technician_not_allowed': 'This person cannot work on these records.',
  'errors.field.technician_not_in_group': 'This technician is not a member of the chosen group.',
  'errors.field.template_disabled': 'This template was turned off. Choose another template.',
  'errors.field.template_not_found': 'That template no longer exists. Choose another one.',
  'errors.field.template_not_offered':
    'This template is not offered to you. Choose another template.',
  'errors.field.time_format_unknown': 'Choose 24-hour or 12-hour time.',
  'errors.field.time_zone_unknown': 'Choose a time zone from the list.',
  'errors.field.timezone_required': 'Include a time zone.',
  'errors.field.title_required': 'Enter a title.',
  'errors.field.too_deep': 'Categories have at most three levels.',
  'errors.field.too_many': 'Too many recipients.',
  'errors.field.too_many_actions': 'A rule can have at most {{max}} actions.',
  'errors.field.too_many_addresses': 'Keep at most 20 addresses informed.',
  'errors.field.too_many_approvers': 'A stage can have at most 10 approvers.',
  'errors.field.too_many_assets': 'A record can have at most {{max}} assets.',
  'errors.field.too_many_categories': 'An item can also appear in at most five other categories.',
  'errors.field.too_many_conditions': 'The filter has too many conditions.',
  'errors.field.too_many_copies': 'Make 1 to {{max}} copies at a time.',
  'errors.field.too_many_decimals': 'Use at most {{max}} decimal places.',
  'errors.field.too_many_items': 'There are too many entries.',
  'errors.field.too_many_keywords': 'Use at most 20 keywords per language.',
  'errors.field.too_many_levels': 'At most {{max}} escalation levels per target.',
  'errors.field.too_many_options': 'A question can have at most 50 choices.',
  'errors.field.too_many_questions': 'A form can have at most 30 questions.',
  'errors.field.too_many_recipients': 'Up to 50 people and 20 groups.',
  'errors.field.too_many_records': 'Choose at most {{max}} records.',
  'errors.field.too_many_tasks': 'A plan can have at most 20 tasks.',
  'errors.field.too_many_values': 'Choose at most {{max}}.',
  'errors.field.topic_too_deep': 'Topics can be at most {{max}} levels deep.',
  'errors.field.topic_under_itself': 'A topic cannot go under itself or one of its subtopics.',
  'errors.field.trusted_servers_too_many': 'Name 5 servers at most.',
  'errors.field.type_cannot_change':
    "A field's type cannot change. Add a new field and retire this one.",
  'errors.field.unknown_article_type': 'This article type does not exist or is retired.',
  'errors.field.unknown_builtin_report': 'This built-in report does not exist.',
  'errors.field.unknown_category': 'One of these categories does not exist here.',
  'errors.field.unknown_column': 'This column does not exist for these records.',
  'errors.field.unknown_dimension': 'Reports cannot be grouped by this field.',
  'errors.field.unknown_entity': 'There is nothing of this kind to report on.',
  'errors.field.unknown_field': 'You cannot filter on this field.',
  'errors.field.unknown_folder': 'This folder does not exist any more.',
  'errors.field.unknown_group': 'One of these groups does not exist here.',
  'errors.field.unknown_key': 'This filter setting is not recognised.',
  'errors.field.unknown_language': 'Only English, Arabic and Urdu names are supported.',
  'errors.field.unknown_measure': 'This measure is not available for these records.',
  'errors.field.unknown_operator': 'This comparison is not recognised.',
  'errors.field.unknown_option': "This choice is not one of the question's options.",
  'errors.field.unknown_parameter': 'This list option is not recognised.',
  'errors.field.unknown_permission': 'This permission does not exist.',
  'errors.field.unknown_placeholder': "Use only the form's question keys, or {person}, in braces.",
  'errors.field.unknown_priority': 'Choose a priority from the list.',
  'errors.field.unknown_question': 'This form has no such question.',
  'errors.field.unknown_recipient':
    'Someone chosen is no longer active, or a group no longer exists.',
  'errors.field.unknown_record_type': 'Choose what the rule applies to.',
  'errors.field.unknown_reference': 'A person or group named here no longer exists.',
  'errors.field.unknown_role': 'This role does not exist here. Choose one from the list.',
  'errors.field.unknown_sort_field': 'The list cannot be sorted by this field.',
  'errors.field.unknown_stage': 'This type has no such stage.',
  'errors.field.unknown_time_zone': 'Choose a time zone from the list.',
  'errors.field.unknown_value': 'This value does not exist (any more).',
  'errors.field.unknown_variable':
    'This uses a variable that does not exist. Pick one from the list.',
  'errors.field.url_not_valid': 'Enter a web address starting with https:// or http://.',
  'errors.field.user_not_found': 'This person does not exist in your organisation.',
  'errors.field.value_no_longer_valid': 'This value is no longer available.',
  'errors.field.value_not_allowed': 'This comparison does not take a value.',
  'errors.field.value_required_by_system':
    '"Other" cannot be retired: it is the way out when no reason fits.',
  'errors.field.value_too_long': 'This value is too long.',
  'errors.field.value_too_long_max': 'Use at most {{max_length}} characters.',
  'errors.field.value_too_short': 'Use at least {{min}} characters.',
  'errors.field.vendor_inactive': "This vendor is inactive and can't be picked.",
  'errors.field.vendor_name_taken': 'Another vendor has this name.',
  'errors.field.vendor_not_found': 'This vendor no longer exists.',
  'errors.field.week_empty': 'Add at least one working period.',
  'errors.field.week_start_unknown': 'Choose the day the week starts.',
  'errors.field.week_too_many_periods': 'A week can have at most 28 working periods.',
  'errors.field.whole_number_required': 'Enter a whole number.',
  'errors.field.wider_than_topic':
    "An article can only narrow its topic's audience, never widen it.",
  'errors.field.window_end_before_start': 'Must be after the start.',
  'errors.field.workflow_disabled': 'This workflow is switched off. Switch it on first.',
  'errors.field.workflow_not_found': 'Choose a workflow that exists.',
  'errors.field.workflow_not_published': 'Publish this workflow first.',
  'errors.field.workflow_wrong_record_type': 'This workflow is for another kind of record.',
  'errors.field.would_loop': 'A release cannot be part of itself, directly or through others.',
  'errors.file_link_expired': 'The link expired. Open the file again.',
  'errors.file_not_an_image': 'This file is not an image.',
  'errors.file_not_found': 'This file does not exist or you cannot see it.',
  'errors.file_not_ready': 'This file is not ready to open.',
  'errors.file_not_rescannable': 'This file cannot be checked again.',
  'errors.file_owner_not_allowed': 'Files cannot be attached there.',
  'errors.file_owner_not_found': 'What you are attaching to does not exist or you cannot see it.',
  'errors.file_staff_only':
    "Only the service desk can remove files or add them to someone else's message.",
  'errors.file_thumbnail_not_found': 'This file has no preview.',
  'errors.file_too_large': 'The file is larger than the limit of {{limit_mb}} MB.',
  'errors.file_type_blocked': 'Files of this type are not allowed (.{{extension}}).',
  'errors.files_not_configured': 'Files cannot be stored: file encryption keys are not configured.',
  'errors.follower_not_found': 'This person is not following it.',
  'errors.group_not_found': 'The support group was not found.',
  'errors.group_not_led': 'You can only manage the groups you lead.',
  'errors.handoff_invalid': 'This sign-in has expired or was already used. Please sign in again.',
  'errors.holiday_list_not_found': 'This holiday list does not exist or was deleted.',
  'errors.holiday_not_found': 'This holiday does not exist or was deleted.',
  'errors.ical_too_large': 'The file is larger than 1 MB.',
  'errors.idempotency_key_reused':
    'This request was already used for different data. Start a new request.',
  'errors.idempotency_request_in_progress':
    'The same request is still being processed. Please wait a moment.',
  'errors.identity_admin_not_configured':
    'Sign-in settings are not set up on this installation yet. Ask your administrator to run the identity set-up step.',
  'errors.identity_admin_unavailable':
    'The sign-in service cannot be reached right now. Try again in a moment.',
  'errors.identity_organization_missing':
    'Your organisation is not set up for sign-in yet. Ask your administrator.',
  'errors.identity_provider_unavailable':
    'Sign-in is temporarily unavailable. Please try again shortly.',
  'errors.incident_has_problem':
    'This incident is already linked to {{display_id}}. Move it to confirm.',
  'errors.insert_too_large':
    "The article's images are too large to insert together: at most {{limit_mb}} MB.",
  'errors.instance_not_failed': 'Only a failed workflow can be retried.',
  'errors.instance_not_running': 'This workflow is not running, so it cannot be stopped.',
  'errors.instance_running': 'Stop this workflow before running it again.',
  'errors.instances_not_in_workflow':
    'Some of the chosen runs are not runs of this workflow ({{count}}).',
  'errors.interactive_session_required':
    'Do this in the web console while signed in. API keys and the mobile app cannot.',
  'errors.internal_error': 'Something went wrong on our side. Please try again.',
  'errors.invalid_choice': 'This value is not one of the choices.',
  'errors.invalid_cursor': 'This page link is no longer valid. Please reload the list.',
  'errors.invalid_date': 'Enter a date such as 2026-11-30.',
  'errors.invalid_etag':
    'The item version sent with this change is not valid. Reload and try again.',
  'errors.invalid_filter': 'The filter could not be applied. Check the highlighted condition.',
  'errors.invalid_idempotency_key': 'The request identifier is not valid.',
  'errors.invalid_login_state': 'This sign-in link has expired. Please start again.',
  'errors.invalid_mobile_challenge':
    'The app could not start signing in. Please update the app and try again.',
  'errors.invalid_number': 'Enter a number.',
  'errors.invalid_page_size': 'Too many rows were requested for one page.',
  'errors.invalid_report': 'This report cannot run as it is. Check the highlighted parts.',
  'errors.invalid_sort': 'The list cannot be sorted this way.',
  'errors.invalid_tenant_id': 'The organisation identifier is not valid.',
  'errors.invalid_transition':
    'This is not possible in the current status. Reload to see the latest.',
  'errors.invalid_value': 'This value is not valid.',
  'errors.investigator_not_found': 'This person is not an investigator of this problem.',
  'errors.invitation_already_signed_in':
    'This person has signed in already, so there is nothing to invite them to.',
  'errors.invitation_needs_email': 'Add an email address to this person first.',
  'errors.invitation_not_found': 'This invitation was not found.',
  'errors.invitation_not_pending':
    'This invitation is no longer waiting: it was accepted or withdrawn.',
  'errors.invitation_pending': 'This person has an invitation waiting. Send it again instead.',
  'errors.invitation_person_cannot_sign_in':
    'This person is deactivated or not allowed to sign in.',
  'errors.ip_not_allowed':
    'Your organisation does not allow sign-in from this network. Connect from an allowed network, or ask your administrator.',
  'errors.job_kind_not_available': 'This kind of job is not available yet.',
  'errors.job_size': 'Choose between 1 and {{max}} runs.',
  'errors.kb_article_not_editable':
    'You cannot edit this article. Its owner or a knowledge manager can.',
  'errors.kb_article_not_found': 'This article does not exist or is not shared with you.',
  'errors.kb_article_not_published': 'This article has no published version to insert yet.',
  'errors.kb_article_withdrawn': 'This article is no longer available.',
  'errors.kb_cannot_approve':
    "You cannot approve this article. The topic's owner or an approver can.",
  'errors.kb_cannot_delete': 'You cannot move this article to the trash.',
  'errors.kb_cannot_withdraw': 'You cannot withdraw this article.',
  'errors.kb_draft_exists': 'A draft in this language is already open. Continue that one.',
  'errors.kb_draft_in_review': 'This version is in review and cannot be changed now.',
  'errors.kb_draft_not_found': 'There is no draft of this article in that language.',
  'errors.kb_link_not_found': 'This link no longer exists.',
  'errors.kb_not_a_draft': 'Only a draft can be sent for review.',
  'errors.kb_not_in_review': 'This version is not waiting for review.',
  'errors.kb_not_published': 'This article is not published yet.',
  'errors.kb_record_has_no_resolution': 'This record has no resolution to save as knowledge yet.',
  'errors.kb_record_not_found': 'This record does not exist or is not shared with you.',
  'errors.kb_requesters_off': 'Knowledge articles are not available here.',
  'errors.kb_self_approval_off':
    'Authors cannot approve their own articles here. Ask another approver.',
  'errors.kb_topic_in_trash':
    'Its topic is in the trash. Restore the topic first, or choose another topic.',
  'errors.kb_topic_not_found': 'This topic does not exist or is not shared with you.',
  'errors.kb_type_not_found': 'This article type does not exist.',
  'errors.kb_version_not_published':
    'That version is no longer the one readers see. Reload the article and try again.',
  'errors.kb_vote_comment_too_long': 'Keep the comment to 1,000 characters.',
  'errors.kb_vote_reason_for_no_only': 'A reason goes with "No" only.',
  'errors.kb_vote_reason_unknown': 'Choose one of the reasons offered.',
  'errors.last_break_glass_admin':
    'This is the last emergency administrator while single sign-on is required. Name another first, or stop requiring single sign-on.',
  'errors.last_tenant_admin': 'The organisation must keep at least one tenant administrator.',
  'errors.ldap_attribute_invalid': 'Enter a directory attribute name: letters, digits and hyphens.',
  'errors.ldap_bind_password_missing': 'No bind password is stored. Enter it again.',
  'errors.ldap_dn_invalid': 'Enter a distinguished name such as OU=People,DC=example,DC=com.',
  'errors.ldap_federation_keycloak_unavailable':
    'The identity service did not answer. The directory will be connected when it is back.',
  'errors.ldap_federation_not_installed':
    'AD/LDAP is not turned on for this installation. Ask your administrator to enable it.',
  'errors.ldap_federation_refused':
    'The identity service refused the directory settings. Check the server, bind account and paths.',
  'errors.ldap_filter_invalid': 'Enter an LDAP filter in brackets, such as (objectClass=person).',
  // WP-040 AD/LDAP (D-130)
  'errors.ldap_host_invalid':
    "Enter the directory server's host name or IP address, without ldap:// or a path.",
  'errors.ldap_single_tenant_only':
    'AD/LDAP directories can only be connected on an installation that serves one organisation.',
  'errors.lifecycle_draft_exists':
    'This life cycle already has a draft. Open it, or throw it away first.',
  'errors.lifecycle_draft_not_found': 'This life cycle has no draft. Start one to make changes.',
  'errors.lifecycle_version_has_problems_one':
    'The draft has {{count}} problem to fix before it can be published.',
  'errors.lifecycle_version_has_problems_other':
    'The draft has {{count}} problems to fix before it can be published.',
  'errors.lifecycle_version_last_published':
    'Version {{number}} is the one new records start on, so it cannot be retired.',
  'errors.lifecycle_version_not_found': 'This life cycle version was not found.',
  'errors.lifecycle_version_not_published': 'Only a published version can be retired.',
  'errors.limit_reached':
    'Your plan’s limit for this has been reached. Ask your administrator to extend the plan.',
  'errors.link_has_own_route':
    'This link is removed in its own place: unlink the incident, or undo the merge.',
  'errors.link_not_found': 'This link does not exist, or it was removed.',
  'errors.linked_records_not_available': 'Linked records are not available yet.',
  'errors.list_not_found': 'This list does not keep settings.',
  'errors.login_failed': 'Sign-in did not complete. Please try again.',
  'errors.login_not_this_browser':
    'This sign-in was started in another browser or has expired. Please sign in again here.',
  'errors.mail_address_invalid': 'An email address is not valid.',
  'errors.mail_attachment_name': 'An attachment name is not valid.',
  'errors.mail_attachment_type': 'This type of file cannot be sent by email.',
  'errors.mail_attachments_too_large': 'The attachments are larger than 10 MB together.',
  'errors.mail_block_rule_exists': 'A rule for this already exists.',
  'errors.mail_block_rule_not_found': 'This block rule does not exist.',
  'errors.mail_block_rules_full': 'There can be {{max}} block rules at most. Remove one first.',
  'errors.mail_content_gone': "This e-mail's text is no longer kept. Write the reply again.",
  'errors.mail_kind_invalid': 'This kind of email is not known.',
  'errors.mail_language_invalid': 'This language is not available for email.',
  'errors.mail_not_configured':
    'Outgoing mail is not set up on this installation. Ask your operator to configure it.',
  'errors.mail_not_waiting': 'This message is no longer waiting: someone handled it already.',
  'errors.mail_recipients': 'Send to between 1 and 50 recipients.',
  'errors.mail_sender_invalid': 'The sender name or reply-to address is not valid.',
  'errors.mail_status_staff_only': 'Only people who reply on records can see this.',
  'errors.mail_subject_invalid': 'The subject must be one line of at most 300 characters.',
  'errors.mailbox_address_taken': 'Another mailbox already reads this address.',
  'errors.mailbox_credential_unreadable':
    "The app's secret or certificate is missing or cannot be read. Enter it again.",
  'errors.mailbox_key_ring_missing':
    "Mailbox passwords cannot be stored safely yet: the installation's key ring is not set up.",
  'errors.mailbox_not_found': 'This mailbox does not exist.',
  'errors.mailbox_sign_in_not_needed': 'This mailbox does not need anyone to sign in.',
  // WP-040 session 2: directory sync.
  'errors.managed_by_directory': 'Your directory keeps this field. Change it there.',
  'errors.measure_not_permitted':
    'You may not see this figure: it needs access to its data (for asset money, the right to see financials).',
  'errors.message_refused': 'The mail server refused the message.',
  'errors.method_not_allowed': 'This action is not supported here.',
  'errors.mfa_enrolment_unavailable':
    'Two-step sign-in has to be set up first, but the sign-in service cannot be reached. Try again in a moment.',
  'errors.mfa_reset_not_signed_in':
    'This person has not signed in yet, so there is nothing to reset.',
  'errors.mfa_reset_own': 'You cannot reset your own two-step sign-in. Ask another administrator.',
  'errors.name_taken': 'This name is already used.',
  'errors.network_error':
    'SupportX cannot be reached right now. Check your connection; we will keep trying.',
  'errors.no_organization':
    'Your account is not linked to any organisation yet. Please contact your administrator.',
  'errors.node_not_found': 'That step is not in this version of the workflow.',
  'errors.node_not_mapped': 'A step this run is at has no place in the new version: map it to one.',
  'errors.not_a_member': 'You are not a member of that organisation.',
  'errors.not_a_person': 'This is a service identity, not a person: it has no cost per hour.',
  'errors.not_acceptable': 'The requested format is not supported.',
  'errors.not_an_approver': 'You are not an approver of this request.',
  'errors.not_cancelable_from_here': 'It cannot be cancelled from where it is now.',
  'errors.not_closable_from_here': 'It cannot be closed from where it is now. Move it on first.',
  'errors.not_found': 'The item was not found.',
  'errors.not_known_error': '{{display_id}} is not a known error.',
  'errors.not_merged': '{{display_id}} is not merged, so there is nothing to undo.',
  'errors.not_resolved': 'This is no longer waiting for your answer: it is not resolved now.',
  'errors.not_visible': 'You cannot see this change, so it was left as it is.',
  'errors.nothing_to_override':
    'This change is not waiting for approval again, so there is nothing to override.',
  'errors.nothing_to_retry': 'There is no failed step to run again.',
  'errors.notification_event_not_found': 'This notification event does not exist.',
  'errors.notification_not_found': 'This notification does not exist or is not yours.',
  'errors.notification_record_not_found': 'This record does not exist or is not available to you.',
  'errors.notification_rule_locked':
    'This is a security notice: no one can switch it off, change who gets it or reset it.',
  'errors.notify_link_not_found':
    'This link no longer works. It may have been used already, or it has expired.',
  'errors.on_behalf_out_of_scope':
    "You can't raise a request for this person. Ask your service desk.",
  'errors.open_work_blocked': 'This cannot be done while this work is open: {{items}}.',
  'errors.open_work_unconfirmed': 'Work is still open: {{items}}. Confirm to go ahead anyway.',
  'errors.order_out_of_date': 'The list changed meanwhile. Reload it and order again.',
  'errors.out_of_range': 'This value is outside the allowed range.',
  'errors.own_profile_only': 'You can only change your own preferences.',
  'errors.parallel_in_progress':
    'This run is inside parallel branches and cannot move until they join.',
  'errors.password_policy_not_saved': 'Save the password policy first.',
  'errors.password_policy_platform': 'The platform sets the password policy on this installation.',
  'errors.password_reset_not_signed_in':
    'This person has not signed in yet. Send them an invitation instead.',
  'errors.payload_too_large': 'The upload is too large.',
  'errors.people_import_file_not_readable': 'Use a CSV file or an Excel workbook ({{xlsx}}).',
  'errors.people_import_file_too_large': 'The file is larger than 5 MB.',
  'errors.people_import_file_unsafe':
    'The workbook was not opened: it unpacks to far more than its size.',
  'errors.permission_denied': 'You do not have permission to do this.',
  'errors.pick_list_not_found': 'That list does not exist.',
  'errors.pick_list_value_not_found': 'That value no longer exists.',
  'errors.plain_connection_refused':
    'A connection without encryption is refused unless you allow it.',
  'errors.plan_section_not_found': 'This plan section does not exist.',
  // WP-008: API conventions (concurrency, idempotency, filters, sorting, paging).
  'errors.precondition_required':
    'This change needs the version you are editing. Reload the item and try again.',
  'errors.private_key_unreadable':
    'The private key cannot be read: paste it unencrypted in PEM format.',
  'errors.privilege_escalation': 'You cannot give access you do not have yourself.',
  'errors.problem_closed': '{{display_id}} is closed, so it cannot be merged.',
  'errors.quick_sign_in_not_configured':
    'Quick sign-in isn’t set up on this stack: run make dev-quick-sign-in.',
  'errors.quick_sign_in_refused': 'Keycloak refused this quick sign-in.',
  'errors.quick_sign_in_wait':
    'This persona signed in twice in the last 30 seconds. Try again in {{seconds}} seconds.',
  'errors.range_not_satisfiable': 'That part of the file does not exist.',
  'errors.rate_limited': 'Too many requests. Please wait a moment and try again.',
  // Entitlements (WP-009)
  'errors.read_only_mode':
    'Your organisation is in read-only mode. You can view and export data, but changes are paused until the licence is renewed.',
  'errors.realtime_channel_denied':
    'You can no longer follow this live. Reload the page to see the latest data.',
  'errors.realtime_not_configured':
    'Live updates are not set up on this server. Reload the page to see the latest data.',
  'errors.reauth_failed': 'That did not confirm it was you. Nothing was changed.',
  'errors.reauth_required': 'Confirm it is you to continue: sign in again, then try once more.',
  'errors.reauth_unavailable':
    'Your organisation signs you in through a provider that cannot confirm it again on request. Ask an administrator.',
  'errors.recipient_deferred': "The recipient's mail server asked to try later.",
  'errors.recipient_refused': 'The mail server refused the recipient.',
  'errors.record_closed': 'Closed and cancelled records cannot be changed.',
  'errors.record_not_editable': 'You need to be able to edit the record to do this.',
  'errors.reference_copied': 'Reference copied',
  'errors.reference_is': 'Reference: {{reference}}',
  'errors.release_not_failed':
    "Follow-ups are offered once the release's deployment has failed or been rolled back.",
  'errors.reminder_not_found': 'This reminder is no longer there.',
  'errors.repeat_hit_not_found': 'This set of repeated incidents no longer exists.',
  'errors.repeat_rule_not_found': 'This repeat incident rule no longer exists.',
  'errors.reply_template_not_found': 'This reply template no longer exists.',
  'errors.report_entity_not_found': 'There is nothing of this kind to report on.',
  'errors.report_export_not_found': 'This export does not exist or is not yours.',
  'errors.report_export_not_ready':
    'This file is not ready, or its link has expired. Export the report again.',
  'errors.report_not_allowed': 'You do not have permission to run reports on these records.',
  'errors.report_not_editable':
    'Only the owner, or someone who manages shared folders, can change this report. Copy it to make your own.',
  'errors.report_not_found': 'This report does not exist or is not shared with you.',
  'errors.report_queue_full':
    'Your organisation is running many reports right now. Please try again in a few seconds.',
  // Reports (WP-035)
  'errors.report_schedule_not_found': 'This schedule does not exist or is not yours.',
  'errors.report_timeout':
    'The report took longer than {{seconds}} seconds and was stopped. Narrow the date range or the filters and try again.',
  'errors.required': 'This field is required.',
  'errors.restart_at_end': 'Choose a step to run from, not an end.',
  'errors.role_in_use':
    'This role is still assigned to users. Choose a role to move them to first.',
  'errors.role_not_found': 'This role was not found.',
  'errors.rule_not_found': 'This rule no longer exists.',
  'errors.rule_refused': '{{message}}',
  'errors.saved_search_limit': 'You have reached the limit of saved searches. Delete one first.',
  'errors.saved_search_not_found': 'This saved search does not exist.',
  'errors.saved_view_not_found': 'This saved view no longer exists, or it is not yours.',
  'errors.scale_value_not_found': 'That value does not exist.',
  'errors.server_busy': 'The mail server was busy.',
  'errors.service_category_in_use':
    'This category still holds items or categories. Move or delete them first.',
  'errors.service_category_not_found': 'This category does not exist.',
  'errors.service_identity_managed':
    'This is a connector’s own identity. Change it from Admin › Integrations.',
  'errors.service_identity_roles_elsewhere':
    'A workflow’s or connector’s own identity gets its roles from its own settings, not here.',
  'errors.service_unavailable': 'The service is temporarily unavailable. Please try again shortly.',
  'errors.session_expired': 'Your session has ended. Please sign in again.',
  'errors.session_key_still_in_use':
    'This server cannot start: a sign-in key it no longer lists is still needed. List the key again.',
  'errors.session_not_found': 'That session has already ended or isn’t one of yours.',
  'errors.sign_in_not_allowed': 'Sign-in is turned off for your account. Ask your administrator.',
  'errors.sign_in_unavailable':
    'Signing in is not available right now. Please wait a minute and try again.',
  'errors.sign_in_unknown_person':
    'Your organisation has not added you to SupportX yet. Contact your service desk to get access.',
  'errors.site_not_found': 'The site was not found.',
  'errors.skip_without_next':
    'This step has no single next step to move on to, so it cannot be skipped; retry it or run the workflow again from a chosen step.',
  'errors.sla_fallback_required':
    'The default policy cannot be deleted: it applies when no other policy does.',
  'errors.sla_policy_not_found': 'This SLA policy does not exist or was deleted.',
  'errors.sla_record_type_not_found': 'Service targets are not available for this kind of record.',
  'errors.sla_target_done':
    'This SLA target is already met or stopped, so its due date can no longer change.',
  'errors.sla_target_not_found': 'This incident has no such SLA target.',
  'errors.special_hours_not_found': 'These special hours do not exist or were removed.',
  'errors.sso_not_tested': 'Test the set-up with a sign-in before switching it on.',
  'errors.sso_provider_limit': 'You can have at most {{max}} single sign-on set-ups.',
  'errors.sso_provider_missing':
    'This set-up is missing in the sign-in service. Remove it and add it again.',
  'errors.sso_provider_not_found': 'This single sign-on set-up was not found.',
  'errors.sso_provider_refused':
    'The sign-in service refused these settings. Check them and try again.',
  'errors.sso_required':
    "Your organisation requires single sign-on. Sign in with your organisation's account instead of a password.",
  'errors.sso_required_needs_break_glass':
    'Name at least one emergency (break-glass) administrator with two-step sign-in before requiring single sign-on.',
  'errors.sso_switch_off_first':
    'Switch the set-up off before changing how it connects, so nobody is locked out.',
  'errors.sso_switched_off': 'Switch the set-up on, or change it, before testing it.',
  'errors.sso_test_not_found': 'This test has ended. Start a new one.',
  'errors.stage_move_not_allowed':
    'This move is not allowed from the current status. Reload to see the latest.',
  'errors.stage_move_refused':
    'Something must be done before this move. See the reasons on the record.',
  'errors.stage_not_found': 'This stage does not exist.',
  'errors.stage_path_disabled': 'That path is switched off for new records.',
  'errors.stage_status_system_only': 'Only an approval decision sets this status.',
  'errors.standard_change_locked':
    'A standard change keeps its plan as approved. Changing it makes this a normal change, which needs normal approval.',
  'errors.status_not_found': 'That status no longer exists.',
  'errors.storage_not_configured': 'File storage is not set up for this installation.',
  'errors.storage_quota_exceeded':
    "Your organisation's file storage is full ({{used_gb}} of {{limit_gb}} GB).",
  'errors.storage_unavailable':
    'File storage cannot be reached. Try again later or contact your administrator.',
  'errors.system_calendar_required':
    'Every organisation keeps this calendar, so it cannot be deleted.',
  'errors.system_role_immutable': 'Built-in roles cannot be changed or deleted.',
  'errors.system_role_not_deletable':
    "Built-in roles can't be deleted. Copy the role to make your own version.",
  'errors.task_blocked': 'This task waits for {{task}} to be done first.',
  'errors.task_template_not_found':
    'This task template is no longer there or is no longer offered.',
  'errors.technician_limit_reached':
    'All technician seats in your organisation’s plan are in use. Ask your administrator to free a seat or add more.',
  'errors.technicians_only': 'Only technicians can see other users.',
  'errors.template_not_found': 'That template no longer exists.',
  'errors.tenant_admin_is_technician':
    'A tenant administrator stays a technician. Remove the administrator role first.',
  'errors.tenant_not_found': 'Your organisation could not be found.',
  'errors.tenant_not_provisioned':
    'Your organisation is not set up in SupportX yet. Please contact your administrator.',
  'errors.tenant_suspended': 'Your organisation’s access is suspended.',
  'errors.timer_not_running': 'You have no timer running on this record.',
  'errors.timer_record_done':
    'This record is resolved or closed. Log the time as a worklog instead.',
  'errors.timer_running': 'Your timer is already running on this record.',
  'errors.too_many_favourites': 'You can star up to {{max}} reports.',
  'errors.too_many_files': 'Too many files at once: at most {{max}}.',
  'errors.too_many_moves': 'A life cycle can have at most {{max}} moves.',
  'errors.too_many_rules': 'At most {{max}} rules per record type.',
  'errors.transition_condition_not_met':
    'This status change is not available to you on this record now.',
  'errors.transition_not_allowed': 'This status change is not available to you on this record.',
  'errors.transition_not_found': 'That status change is not part of the life cycle.',
  'errors.unauthenticated': 'Please sign in to continue.',
  'errors.unknown_record_type': 'Automation is not available for this kind of record.',
  'errors.unsupported_media_type': 'This file or content type is not supported.',
  'errors.user_disabled': 'Your account has been disabled. Please contact your administrator.',
  'errors.user_email_conflict':
    'Another account in your organisation already uses this email address.',
  'errors.user_not_found': 'The user was not found.',
  'errors.validation_failed': 'Some fields need your attention.',
  'errors.vendor_in_use': 'Records still name this vendor ({{used}}). Make it inactive instead.',
  'errors.vendor_not_found': 'This vendor no longer exists.',
  'errors.version_conflict':
    'Someone else saved this item after you opened it. Reload to see their changes.',
  'errors.window_not_found': 'This window does not exist, or it was removed.',
  'errors.withdraw_not_allowed': 'Only the requester can withdraw this request.',
  'errors.withdraw_not_pending': 'Only a request awaiting approval can be withdrawn.',
  'errors.work_item_asset_not_found': 'This asset is no longer linked to the record.',
  'errors.work_item_link_not_found': 'This link no longer exists.',
  'errors.work_item_not_found': 'This record does not exist or you cannot see it.',
  'errors.work_item_task_not_found': 'This task no longer exists.',
  'errors.work_item_type_not_found': 'There is no such kind of record.',
  'errors.work_item_view_not_found':
    'This saved view no longer exists, or it is not shared with you.',
  'errors.work_item_worklog_not_found': 'This worklog no longer exists.',
  'errors.workflow_instance_changed':
    'This workflow changed since you opened it. Reload and try again.',
  'errors.workflow_instance_not_found': 'This workflow run was not found.',
  'errors.workflow_job_not_found': 'This job was not found.',
  'errors.workflow_version_not_found': 'That version of the workflow was not found.',
  'errors.worklog_record_closed': "Time can't be logged or changed on a closed record here.",
  'errors.would_lose_access':
    'After this change you will no longer see {{display_id}}. Confirm to hand it over.',
} as const;
