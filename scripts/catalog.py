from internal import SCHEMAS,gacha_table,internal_rows

FIELDS={
    'stages':'id stage_group_id name attribute_id cost cost_type_id difficulty experience boss_num boss_hp_bar0 boss_hp_bar1 boss_hp_bar2 bonus_turn charball_attribute_rate enemy_attribute_rate clear_bonus_char_id extra_stage_id extra_stage2_id extra_stage3_id updated_at',
    'stage_groups':'id name attribute_id stage_class_id stage_class_sub_id boss_skin_id banner_file_name drop_id required_rank request_item_id request_item_cnt start_at end_at released_at updated_at',
    'stage_gimmicks':'id stage_id gimmick_flag highlight_gimmick_flag',
    'stage_phases':'id stage_id enemy_max background_effect_id stage_ground_effect_id skip_rate phase_ext_flag',
    'stage_notes':'id stage_id message display_type',
    'stage_group_notes':'id stage_group_id message display_type',
    'stage_class_catalogs':'id quest_type_id is_limited is_collabo start_at end_at',
    'gacha_groups':'id name description image_id enable cost_cnt cost_item_id output_cnt rarity_min rarity_max request_rank enable_count header_title footer_title button_footer_text parent_group_id previous_step_gacha_group_id require_previous_step_cnt required_gacha_group_id enable_condition_id popup_url category_id type_id updated_at',
    'gachas':'id char_id gacha_group_id selectable_group_id selectable_default selectable_category_id',
    'gacha_group_feature_chars':'id gacha_group_id char_id start_at end_at',
    'gacha_group_extra_cost_items':'id gacha_group_id item_id cost_cnt',
    'gacha_limited_chars':'id char_id status gacha_group_event_kind_id start_at end_at',
    'selectable_pickup_gacha_display_weights':'id group_id display_weight',
    'chars':'id name rarity attribute_id skin_id drop_id level_max hp hp_max attack attack_max power power_max hit_type fight_type species_id strike_shot_id entry_stage_group_id updated_at',
    'char_skills':'id char_id name description skill_id sort_id',
    'strike_shots':'id name description require_cnt',
    'items':'id name description',
    'texts':'id label text',
    'weekly_max_luck_bonus_abilities':'id level ability_type value description',
    'stage_group_banners':'id stage_group_id file_name priority type_id start_at end_at',
    'box_gacha_items':'id gacha_group_id item_id cnt rarity stock unlimited',
    'seal_items':'id item_id display_id rarity type_id seal_item_group_id image_name',
    'seal_item_groups':'id name category sort_id',
    'seal_events':'id name start_at end_at',
    'inherited_special_gacha_events':'id gacha_group_id gacha_group_event_id display_start_at display_end_at receivable_end_at banner_name button_text',
    'defer_payment_gacha_events':'id gacha_group_id gacha_group_event_id display_start_at display_end_at receivable_start_at receivable_end_at banner_name button_text sns_text',
    'storage_favorite_gacha_events':'id gacha_group_id gacha_group_event_id display_start_at display_end_at receivable_end_at initialize_gacha_group_id banner_name button_text',
    'login_power_up_gacha_events':'id gacha_start_at gacha_end_at power_up_start_at power_up_end_at power_texts1 power_texts2 power_texts3',
    'auto_gacha_events':'id gacha_group_event_id start_at end_at receivable_end_at purchase_item_id',
    'seethrough_gacha_events':'id start_at end_at description',
}
FIELDS['chars']+=' collection_enable_at sort_id time_limited virtual_char_id char_ability_id shot_skill_id enhanced_strike_shot_id luck_skill_id'
FIELDS['stage_groups']+=' enable_condition_id ext_flag ext_flag_2 event_kind_id test_flag sort_id ui_group_id view_texts_id skin_timeline_name invalid_quest_drop_info enable_playable_time'
for name in ['shot_skills','char_evolutions']:FIELDS[name]=' '.join(SCHEMAS[name]['fields'])
CATALOG_TABLES=set(FIELDS)
GIMMICK_MASKS=[2,1,4,24,32,64,128,256,2048,4096,512,1024]
GIMMICK_TEXT_IDS=[0x144df23b,0x8d44a381,0xfa439317,0x642706b4,0x13203622,0x8a296798,0xfd2e570e,0x6d914a9f,0x32c34b61,0xe5711e67,0x1a967a09,0x45c47bf7]

def gimmick_labels(rows):
    by_hash={zlib.crc32(row['label'].encode('utf-8'))&0xffffffff:row['text'] for row in rows if isinstance(row.get('label'),str) and isinstance(row.get('text'),str)}
    result=[]
    for mask,text_id in zip(GIMMICK_MASKS,GIMMICK_TEXT_IDS):
        text=by_hash.get(text_id)
        match=re.search(r'\[GIMMICK:([^\]]+)\]',text) if text else None
        result.append({'mask':mask,'textId':text_id,'label':match.group(1) if match else None,'description':text})
    return result

def build_catalog(tables,timestamp,evidence,stage_events):
    public={name:[{key:row[key] for key in fields.split() if key in row} for row in tables[name]] for name,fields in FIELDS.items()}
    for name,rows in tables.items():
        if gacha_table(name) or name=='item_texts':public[name]=internal_rows(name,rows)
    for name in ['stages','stage_groups','gacha_groups','chars']:
        rows=public[name]
        if not rows or any(type(row.get('id')) is not int or not isinstance(row.get('name'),str) for row in rows):
            raise ValueError(f'Invalid catalog identity: {name}')
        if len({row['id'] for row in rows})!=len(rows):
            raise ValueError(f'Duplicate catalog identity: {name}')
    ids={name:{row['id'] for row in public[name]} for name in ['stages','stage_groups','gacha_groups','chars']}
    relations=[]
    for source,key,target in [('stages','stage_group_id','stage_groups'),('stage_gimmicks','stage_id','stages'),('gachas','gacha_group_id','gacha_groups'),('gachas','char_id','chars'),('char_skills','char_id','chars')]:
        references=[row[key] for row in public[source]]
        relations.append({'source':source,'field':key,'target':target,'references':len(references),'resolved':sum(value in ids[target] for value in references),'unresolved':sorted(set(references)-ids[target])})
    return {'schemaVersion':1,'updatedAt':timestamp,'tables':public,'gimmicks':gimmick_labels(public['texts']),'verification':[row for row in evidence if row['table'] in public],'relations':relations,'stageEvents':stage_events,'community':{'status':'not-fetched','description':'ステージごとのクリア使用実績は別途取得が必要です。'},'gachaEvents':[],'gachaScheduleStatus':'not-fetched','weeklyMaxLuckBonuses':[],'weeklyMaxLuckBonusesStatus':'not-fetched','recommendations':[],'gachaBanners':[],'gachaBannersStatus':'not-fetched'}
import re
import zlib
