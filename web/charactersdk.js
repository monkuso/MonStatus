const number=value=>typeof value==='number'&&Number.isFinite(value)?value:null;
const abilityKey=row=>['type_id','target_id','value','name_id'].map(field=>row[field]??0).join(':');

export function abilityNames(effects,definitions,notes=[]){
  const active=effects.filter(row=>row.type_id!==11),groups=new Map();
  for(const row of definitions){const key=row.group_id??row.id;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(row);}
  const consumed=new Set(),selected=[];
  for(const effect of active){
    const key=abilityKey(effect);if(consumed.has(key))continue;
    let best=null;
    for(const group of groups.values()){
      if(!group.some(row=>abilityKey(row)===key)||group.some(row=>consumed.has(abilityKey(row))))continue;
      if(!group.every(row=>active.some(value=>abilityKey(value)===abilityKey(row))))continue;
      if(!best||group.length>best.length)best=group;
    }
    if(!best)continue;
    best.forEach(row=>consumed.add(abilityKey(row)));
    const row=best[0],source=active.find(effect=>abilityKey(effect)===abilityKey(row));
    if(row.name&&row.description)selected.push({name:row.name,description:row.description,gauge:Boolean(source.shot_gauge_level),sourceId:row.id});
  }
  selected.sort((a,b)=>a.sourceId-b.sourceId);
  const note=notes.at(-1);if(note?.description)selected.push({name:note.description,description:'',gauge:false,sourceId:note.id});
  return {normal:selected.filter(row=>!row.gauge),gauge:selected.filter(row=>row.gauge)};
}

export function characterStats(row){
  return [
    {label:'HP',base:number(row.hp_max),plusRaw:number(row.extend_hp_max)},
    {label:'攻撃力',base:number(row.attack_max),plusRaw:number(row.extend_attack_max)},
    {label:'スピード',base:number(row.power_max)===null?null:row.power_max/30,plusRaw:number(row.extend_power_max)===null?null:row.extend_power_max*1.02/30}
  ];
}

export async function loadCharacterInfo(row,{record,related,all}){
  const reference=(table,id)=>typeof id==='number'&&id>0?record(table,id):Promise.resolve(null);
  const [friendships,effects,definitions,notes,species,fights,strikeShot,enhancedStrikeShot,shotSkill,assistSkills,connectSkills]=await Promise.all([
    related('chars',row.id,'char_skills'),related('chars',row.id,'char_efficacious'),all('char_sort_abilities'),related('chars',row.id,'char_efficacious_descriptions'),
    reference('char_species',row.species_id),all('fight_types'),
    reference('strike_shots',row.strike_shot_id),reference('strike_shots',row.enhanced_strike_shot_id),reference('shot_skills',row.shot_skill_id),related('chars',row.id,'assist_skills'),related('chars',row.id,'connect_skills')
  ]);
  const connect=await Promise.all(connectSkills.map(async skill=>({...skill,conditions:await related('connect_skills',skill.id,'connect_skill_conditions'),effects:await related('connect_skills',skill.id,'connect_skill_effects')})));
  return {row,stats:characterStats(row),abilities:abilityNames(effects,definitions,notes),friendships,species,fight:fights.find(value=>value.type_id===row.fight_type)||null,hitType:{0:'反射',1:'貫通'}[row.hit_type]||null,strikeShot,enhancedStrikeShot,shotSkill,assistSkills,connectSkills:connect};
}
