# GitOps 선언 및 서비스 렌더링 결과의 중복 리소스/설정을 검수한다.
from pathlib import Path
import collections
import json
import subprocess
import sys

import yaml
root=Path(__file__).resolve().parents[2]
class StrictLoader(yaml.SafeLoader):
    pass
def mapping(loader,node,deep=False):
    loader.flatten_mapping(node)
    result={}
    for key_node,value_node in node.value:
        key=loader.construct_object(key_node,deep=deep)
        if key in result: raise ValueError('duplicate YAML key %r at line %s'%(key,key_node.start_mark.line+1))
        result[key]=loader.construct_object(value_node,deep=deep)
    return result
StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,mapping)
errors=[]; resources=[]; files=0
cluster={'Namespace','StorageClass','ClusterRole','ClusterRoleBinding','ClusterIssuer','ClusterSecretStore','CustomResourceDefinition','PersistentVolume','ProxyClass'}
def check_unique(items,key,where):
    keys=[key(x) for x in items]
    dup=[k for k,n in collections.Counter(keys).items() if n>1]
    if dup:errors.append('%s duplicates: %s'%(where,dup))
def canonical(x):
    if isinstance(x,dict):return {k:canonical(v) for k,v in sorted(x.items())}
    if isinstance(x,list):return sorted((canonical(v) for v in x),key=lambda v:json.dumps(v,sort_keys=True))
    return x
def inspect(item,where,namespace):
    if not isinstance(item,dict):return
    if 'kind' in item and 'apiVersion' in item and 'metadata' in item:
        meta=item['metadata'];ns='' if item['kind'] in cluster else meta.get('namespace',namespace)
        resources.append(((item['apiVersion'].split('/')[0] if '/' in item['apiVersion'] else '',item['kind'],ns,meta['name']),where))
    if item.get('kind')=='Service':
        ports=item.get('spec',{}).get('ports',[])
        check_unique(ports,lambda v:(v.get('protocol','TCP'),v['port']),where+'/servicePorts')
        check_unique([v for v in ports if 'name' in v],lambda v:v['name'],where+'/servicePortNames')
    if item.get('kind')=='NetworkPolicy':
        for direction in ['ingress','egress']:
            for rule in item.get('spec',{}).get(direction,[]) or []:
                for key in ['to','from','ports']:
                    check_unique(rule.get(key,[]) or [],lambda v:json.dumps(canonical(v),sort_keys=True),where+'/'+direction+'/'+key)
            check_unique(item.get('spec',{}).get(direction,[]) or [],lambda v:json.dumps(canonical(v),sort_keys=True),where+'/'+direction)
    def walk(x,path):
        if isinstance(x,dict):
            for key in ['containers','initContainers','ephemeralContainers']:
                check_unique(x.get(key,[]) or [],lambda v:v['name'],path+'/'+key)
                for container in x.get(key,[]) or []:
                    cpath=path+'/'+key+'/'+container['name']
                    check_unique(container.get('env',[]) or [],lambda v:v['name'],cpath+'/env')
                    check_unique(container.get('ports',[]) or [],lambda v:(v.get('protocol','TCP'),v.get('containerPort')),cpath+'/ports')
                    check_unique([v for v in container.get('ports',[]) or [] if 'name' in v],lambda v:v['name'],cpath+'/portNames')
                    check_unique(container.get('volumeMounts',[]) or [],lambda v:v['mountPath'],cpath+'/mountPaths')
            if 'containers' in x:
                check_unique(x.get('volumes',[]) or [],lambda v:v['name'],path+'/volumes')
            for k,v in x.items():walk(v,path+'/'+str(k))
        elif isinstance(x,list):
            for i,v in enumerate(x):walk(v,path+'/'+str(i))
    walk(item,where)
for p in (root/'gitops').rglob('*.yaml'):
    if '/templates/' in str(p):continue
    files+=1
    try:docs=list(yaml.load_all(p.read_text(),Loader=StrictLoader))
    except Exception as e:errors.append(str(p)+': '+str(e));continue
    if '/operations/' in str(p) or '/charts/' in str(p):continue
    namespace='default'
    application=p.parent.parent/'application.yaml' if p.parent.name=='manifests' else None
    if application and application.exists():
        app=yaml.safe_load(application.read_text());namespace=app.get('spec',{}).get('destination',{}).get('namespace','default')
    for d in docs:
        if not d:continue
        inspect(d,str(p.relative_to(root)),namespace)
        if d.get('kind')=='Application':
            sources=[d.get('spec',{}).get('source',{})]+d.get('spec',{}).get('sources',[])
            for source in sources:
                helm=source.get('helm',{})
                if helm.get('values'):
                    try:values=yaml.load(helm['values'],Loader=StrictLoader)
                    except Exception as e:errors.append(str(p)+' embedded Helm values: '+str(e));continue
                    for extra in values.get('extraDeploy',[]) or []:
                        if isinstance(extra,dict):inspect(extra,str(p.relative_to(root))+' extraDeploy',d['spec']['destination'].get('namespace','default'))
rendercount=0
for p in (root/'gitops-value/values/dev/services').glob('*/values.yaml'):
    files+=1
    try:v=yaml.load(p.read_text(),Loader=StrictLoader)
    except Exception as e:errors.append(str(p)+': '+str(e));continue
    if p.parent.name.startswith('_'):continue
    check_unique(v.get('externalEgress',{}).get('allowedDomains',[]) or [],lambda x:x,str(p)+'/allowedDomains')
    text=subprocess.check_output(['helm','template','dev-'+p.parent.name,str(root/'gitops/charts/generic-service'),'-n',p.parent.name,'-f',str(p)],universal_newlines=True)
    try:docs=list(yaml.load_all(text,Loader=StrictLoader))
    except Exception as e:errors.append('Rendered '+p.parent.name+': '+str(e));continue
    rendercount+=1
    for d in docs:
        if d:inspect(d,'Rendered '+p.parent.name,p.parent.name)
# Alternative workload modes are mutually exclusive deployments, not simultaneous resources.
for p in (root/'gitops-value/values/dev/services').glob('*/values.yaml'):
    if p.parent.name.startswith('_'):continue
    for mode in ['canary','blueGreen']:
        command=['helm','template','dev-'+p.parent.name,str(root/'gitops/charts/generic-service'),'-n',p.parent.name,'-f',str(p),
                                            '--set','canary.enabled='+str(mode=='canary').lower(),'--set','blueGreen.enabled='+str(mode=='blueGreen').lower()]
        rendered=subprocess.check_output(command,universal_newlines=True)
        start=len(resources)
        try:
            for d in yaml.load_all(rendered,Loader=StrictLoader):
                if d:inspect(d,'Rendered '+p.parent.name+' '+mode,p.parent.name)
            check_unique(resources[start:],lambda v:v[0],'Rendered '+p.parent.name+' '+mode+'/resource identities')
        except Exception as e:errors.append('Rendered '+p.parent.name+' '+mode+': '+str(e))
        del resources[start:]
        rendercount+=1
by_id=collections.defaultdict(list)
for rid,where in resources:by_id[rid].append(where)
for rid,sources in by_id.items():
    if len(sources)>1:errors.append('Duplicate resource %s: %s'%(rid,sources))
print('Checked %d YAML files, %d service renders, %d resources'%(files,rendercount,len(resources)))
for e in errors:print('ISSUE',e)
print('Total issues:',len(errors))
sys.exit(1 if errors else 0)
