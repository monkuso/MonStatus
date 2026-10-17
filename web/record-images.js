export function recordImageNames(row){
  const names=[];
  for(const [field,value] of Object.entries(row)){
    if(!/(?:^|_)(?:image|texture|icon|banner|file)(?:_|$)/.test(field)||typeof value!=='string')continue;
    for(const name of value.split('|'))if(/^[A-Za-z0-9_./@-]+\.png$/.test(name)&&!name.split('/').includes('..')&&!names.includes(name))names.push(name);
  }
  return names;
}
export function recordImagePaths(row,assets){
  const paths=[];
  for(const name of recordImageNames(row)){
    for(const path of [assets.events?.[name],assets.items?.[name],assets.quests?.[name],assets.gachas?.[name],...(assets.eventVariants?.[name]||[]).map(x=>x.path),...(assets.itemVariants?.[name]||[]).map(x=>x.path)])if(path&&!paths.includes(path))paths.push(path);
  }
  return paths;
}
