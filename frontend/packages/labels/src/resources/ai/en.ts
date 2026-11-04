// ai labels (see ../README.md). English is the reference.
export const en = {
  'ai_area.knowledge': 'Knowledge',
  'ai_area.predictions': 'Predictions',
  'ai_area.summaries': 'Summaries',
  'ai_area.writing': 'Writing',
  'ai_feature.conversation_summary': 'Conversation summary',
  'ai_feature.possible_duplicates': 'Possible duplicates',
  'ai_feature.reply_draft': 'Reply drafts',
  'ai_feature.text_improve': 'Improve and translate text',
  'ai_outcome.accepted': 'Accepted',
  'ai_outcome.discarded': 'Discarded',
  'ai_outcome.edited': 'Edited',
  'ai_settings.always_masked':
    'The model is outside your installation: personal data is always masked.',
  'ai_settings.confirm_master_off': 'Switch off AI for everyone?',
  'ai_settings.confirm_off': 'Switch off “{{feature}}”?',
  'ai_settings.days': 'days',
  'ai_settings.external': 'outside your installation',
  'ai_settings.features': 'Features',
  'ai_settings.local': 'in your installation',
  'ai_settings.mask_local': 'Mask personal data for the local model too',
  'ai_settings.mask_local_help':
    'Names, e-mail addresses, phone and ID numbers are replaced before the model reads the text. For a model outside your installation this is always on.',
  'ai_settings.master': 'Use AI',
  'ai_settings.master_help': 'Off: no AI feature runs for anyone and no model is called.',
  'ai_settings.model': 'Model',
  'ai_settings.model_value': '{{model}} ({{where}})',
  'ai_settings.no_training':
    'Your AI conversations are never used to train any model. Their text is kept only for the period below, then deleted; every deletion is audited.',
  'ai_settings.off_effect':
    'Switching off removes the feature for everyone at once. Results already made stay in the history but are no longer shown.',
  'ai_settings.privacy': 'Privacy',
  'ai_settings.retention': 'Keep AI call text for',
  'ai_settings.retention_help':
    'After this, the text of each call is deleted; who used which feature and the outcome stay for reports.',
  'ai_settings.saved': 'Saved.',
  'ai_settings.switch_off': 'Switch off',
  'ai_settings.title': 'AI',
  'ai_summary_source.description': 'Description',
  'ai_summary_source.private_notes': 'Private notes',
  'ai_summary_source.public_notes': 'Public notes',
  'ai_summary_source.replies': 'Replies',
  'audit.action.ai.calls_erased': 'Deleted a person\u2019s AI conversation text (erasure)',
  'audit.action.ai.calls_purged': 'Deleted AI conversation text after its retention period',
  'audit.action.ai.settings_changed': 'Changed the AI settings',
  'audit.action.ai.summaries_erased':
    'Deleted the conversation summaries that could name an erased person',
  'errors.ai_call_not_found': 'This AI answer does not exist or is not yours.',
  'errors.ai_feature_off': 'This AI feature is switched off for your organisation.',
  'errors.ai_record_not_visible': 'You cannot see this record, so AI cannot work on it.',
  'errors.ai_summary_nothing':
    'There is nothing to summarise yet: no description, replies or notes.',
  'errors.ai_unavailable': 'The AI model is not answering. Try again in a moment.',
  'errors.field.ai_feature_unknown': 'Choose only features from the list.',
  'errors.field.ai_retention_out_of_range': 'Keep the text between 1 and 365 days.',
  'errors.field.ai_summary_source_unknown':
    'Choose from the description, replies, public notes and private notes.',
  'errors.field.ai_summary_sources_empty': 'Choose at least one part for summaries to read.',
  'event_type.ai.settings.changed': 'AI settings changed',
  'event_type.ai.summary.changed': 'Conversation summary made or out of date',
  'nav.admin_ai': 'AI',
  // AI gateway (WP-037).
  'permission.ai.manage': 'Manage AI',
  'permission.ai.manage.description':
    'Switch AI and its features on or off, choose masking and how long AI call text is kept.',
  'permission_module.ai': 'AI',
} as const;
