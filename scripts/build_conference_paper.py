"""Fill the supplied Strict OOXML conference template without rewriting its styles.

Run with the bundled document Python runtime. The source template is required;
it is a user-supplied document, not downloaded or bundled with the release.
"""
import argparse
import copy
import csv
import hashlib
import json
import re
from pathlib import Path
import zipfile
from lxml import etree as E
from scripts.conference_literature import bibliography
from scripts.conference_content import TITLE, write_body

ROOT = Path(__file__).resolve().parents[1]


def build(template, output):
    source = Path(template).read_bytes()
    z = zipfile.ZipFile(template)
    root = E.fromstring(z.read('word/document.xml'))
    w = root.nsmap['w']; ns = {'w': w}; tag = lambda n: '{' + w + '}' + n
    body = root.find('w:body', ns)
    numbering=E.fromstring(z.read('word/numbering.xml'))
    next_num=max(int(e.get(tag('numId'))) for e in numbering.findall('w:num',ns))+1
    next_abs=max(int(e.get(tag('abstractNumId'))) for e in numbering.findall('w:abstractNum',ns))+1
    def list_definition(fmt):
        nonlocal next_abs
        ident=next_abs;next_abs+=1
        abstract=E.Element(tag('abstractNum'),{tag('abstractNumId'):str(ident)})
        E.SubElement(abstract,tag('multiLevelType'),{tag('val'):'singleLevel'})
        level=E.SubElement(abstract,tag('lvl'),{tag('ilvl'):'0'})
        for name,value in [('start','1'),('numFmt',fmt),('lvlText','%1.'),('suff','space'),('lvlJc','start')]:
            E.SubElement(level,tag(name),{tag('val'):value})
        first_num=numbering.find('w:num',ns)
        numbering.insert(list(numbering).index(first_num),abstract)
        return ident
    def list_instance(abstract):
        nonlocal next_num
        ident=next_num;next_num+=1
        node=E.SubElement(numbering,tag('num'),{tag('numId'):str(ident)})
        E.SubElement(node,tag('abstractNumId'),{tag('val'):str(abstract)})
        if abstract==alpha:
            override=E.SubElement(node,tag('lvlOverride'),{tag('ilvl'):'0'})
            E.SubElement(override,tag('startOverride'),{tag('val'):'1'})
        return ident
    roman=list_definition('upperRoman');alpha=list_definition('upperLetter')
    heading_num=list_instance(roman);subheading_num=None

    paragraphs = body.findall('w:p', ns)
    def role(p):
        found = p.find('w:pPr/w:pStyle', ns)
        return found.get(tag('val')) if found is not None else ''
    patterns = {role(p): p for p in paragraphs if role(p)}
    def para(text, style='BodyText', source_p=None):
        p = E.Element(tag('p'))
        source_p = patterns[style] if source_p is None else source_p
        props = source_p.find('w:pPr', ns)
        if props is not None:
            props = copy.deepcopy(props)
            for sec in props.findall('w:sectPr', ns):props.remove(sec)
            p.append(props)
        # Keep style-level formatting, never the example's red/bold run overrides.
        r = E.SubElement(p, tag('r')); t = E.SubElement(r, tag('t'))
        t.text = text; t.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
        if style=='equation':
            pp=p.find('w:pPr',ns)
            for node in list(pp):
                if node.tag in [tag('rPr'),tag('tabs'),tag('jc'),tag('ind')]:pp.remove(node)
            tabs=E.SubElement(pp,tag('tabs'));E.SubElement(tabs,tag('tab'),{tag('val'):'end',tag('pos'):'4750'})
            E.SubElement(pp,tag('jc'),{tag('val'):'start'})
            E.SubElement(pp,tag('ind'),{tag('firstLine'):'0'})
            p.remove(r)
            m=root.nsmap['m'];mt=lambda n:'{'+m+'}'+n
            math=E.SubElement(p,mt('oMath'))
            def mr(parent,text):
                rr=E.SubElement(parent,mt('r'));E.SubElement(rr,mt('t')).text=text
            def sub(text):
                s=E.SubElement(math,mt('sSub'));mr(E.SubElement(s,mt('e')),'τ');mr(E.SubElement(s,mt('sub')),text)
            mr(math,'τ(s) = ');sub('min');mr(math,' + (');sub('max');mr(math,' − ');sub('min');mr(math,')')
            sup=E.SubElement(math,mt('sSup'));mr(E.SubElement(sup,mt('e')),'(1 − s)');mr(E.SubElement(sup,mt('sup')),'γ')
            rr=E.SubElement(p,tag('r'));E.SubElement(rr,tag('tab'));E.SubElement(rr,tag('t')).text='(1)'
        if style=='tablehead':
            E.SubElement(p.find('w:pPr',ns),tag('keepNext'))
        return p
    def add(text, style='BodyText'):
        nonlocal subheading_num
        p = para(text, style);pp=p.find('w:pPr',ns)
        if style in {'Heading1','Heading2','tablehead','tablefootnote','figurecaption','Heading5'}:
            for child in pp.findall('w:numPr',ns):pp.remove(child)
            np=E.SubElement(pp,tag('numPr'))
            if style=='Heading1':
                subheading_num=list_instance(alpha);ident=heading_num
            elif style=='Heading2':ident=subheading_num
            else:ident=0
            E.SubElement(np,tag('ilvl'),{tag('val'):'0'})
            E.SubElement(np,tag('numId'),{tag('val'):str(ident)})
        body.append(p); return p
    def table(headers, rows, widths):
        sample = root.find('.//w:tbl', ns)
        # Reference table has the intended compact conference grid and borders.
        t = E.Element(tag('tbl'))
        if sample is not None:
            props = sample.find('w:tblPr', ns)
            if props is not None:t.append(copy.deepcopy(props))
        grid = E.SubElement(t, tag('tblGrid'))
        for width in widths:E.SubElement(grid, tag('gridCol'), {tag('w'):str(width)})
        for i, row in enumerate([headers] + rows):
            tr=E.SubElement(t,tag('tr'));trpr=E.SubElement(tr,tag('trPr'))
            E.SubElement(trpr,tag('cantSplit'))
            if i==0:E.SubElement(trpr,tag('tblHeader'))
            for value,width in zip(row,widths):
                tc=E.SubElement(tr,tag('tc'));pr=E.SubElement(tc,tag('tcPr'))
                E.SubElement(pr,tag('tcW'),{tag('w'):str(width),tag('type'):'dxa'})
                p=E.SubElement(tc,tag('p'));pp=E.SubElement(p,tag('pPr'))
                E.SubElement(pp,tag('spacing'),{tag('before'):'30',tag('after'):'30'})
                E.SubElement(pp,tag('jc'),{tag('val'):'center'})
                if i < len(rows):E.SubElement(pp,tag('keepNext'))
                r=E.SubElement(p,tag('r'));rp=E.SubElement(r,tag('rPr'))
                E.SubElement(rp,tag('sz'),{tag('val'):'16'})
                if i==0:E.SubElement(rp,tag('b'))
                E.SubElement(r,tag('t')).text=str(value)
        body.append(t)
    # Retain section carriers and source styles; replace only content slots.
    title=copy.deepcopy(paragraphs[0]); authors=copy.deepcopy(paragraphs[1])
    carriers=[copy.deepcopy(paragraphs[i]) for i in [2,3]]
    main_carrier=next(copy.deepcopy(p) for p in paragraphs if p.find('w:pPr/w:sectPr/w:cols',ns) is not None
                      and p.find('w:pPr/w:sectPr/w:cols',ns).get(tag('num'))=='2')
    final=copy.deepcopy(body.find('w:sectPr',ns))
    sample_table=copy.deepcopy(root.find('.//w:tbl',ns))
    # Keep sample in a detached variable for the table factory after removal.
    def replace_text(p,text):
        for child in list(p):
            if child.tag!=tag('pPr'):p.remove(child)
        r=E.SubElement(p,tag('r'));E.SubElement(r,tag('t')).text=text
    replace_text(title,TITLE)
    replace_text(authors,'Nandana Raj, Harshit Gupta, Vaishnavi Ganesan')
    ar=E.SubElement(authors,tag('r'));E.SubElement(ar,tag('br'));E.SubElement(ar,tag('t')).text='B.Tech. in Computer Science and Engineering'
    for p in carriers:
        replace_text(p,'')
        for cols in p.findall('.//w:cols',ns):cols.set(tag('num'),'1')
    replace_text(main_carrier,'')
    for p in list(body):body.remove(p)
    body.extend([title,authors,*carriers])
    # Table factory retrieves source props from this immutable detached sample.
    # Store source table properties in root temporarily, remove before serialization.
    body.append(sample_table)
    write_body(add,table,None)
    add('References','Heading5')
    original_references=[
        'L. G. Schroeder et al., “Adaptive semantic prompt caching with VectorQ,” arXiv:2502.03771, version 1, 2025. [Online]. Available: https://arxiv.org/html/2502.03771v1',
        'vCache Project, “vCache,” inspected revision 50694eebf0c870231030f73707cb6543d47f0411. [Online]. Available: https://github.com/vcache-project/vCache/tree/50694eebf0c870231030f73707cb6543d47f0411. Accessed: Oct. 26, 2026.',
        'Mistral AI, “ministral-3b-2512,” model documentation. [Online]. Available: https://docs.mistral.ai/models/ministral-3-3b-25-12. Accessed: Oct. 26, 2026.',
        'Mistral AI, “mistral-embed-2312,” model documentation. [Online]. Available: https://docs.mistral.ai/models/mistral-embed-23-12. Accessed: Oct. 26, 2026.',
    ]
    catalog={str(i):text for i,text in enumerate(original_references,1)}
    catalog.update(bibliography())
    citation_order=[]
    citation_map={}
    def cite(match):
        key=match.group(1)
        if key not in catalog:raise ValueError('Unknown citation '+key)
        if key not in citation_map:
            citation_order.append(key);citation_map[key]=len(citation_order)
        return '['+str(citation_map[key])+']'
    for node in body.findall('.//w:t',ns):
        if node.text:node.text=re.sub(r'\[(P?\d+)\]',cite,node.text)
    assert all('P'+str(i) in citation_map for i in range(1,26)), 'Every supplied work must be cited in the body'
    for i,key in enumerate(citation_order,1):
        ref=catalog[key]
        p=add(f'[{i}] '+ref,'references');pp=p.find('w:pPr',ns)
        for child in list(pp):
            if child.tag in [tag('numPr'),tag('jc'),tag('ind')]:pp.remove(child)
        num=E.SubElement(pp,tag('numPr'));E.SubElement(num,tag('numId'),{tag('val'):'0'})
        E.SubElement(pp,tag('jc'),{tag('val'):'start'})
        E.SubElement(pp,tag('ind'),{tag('left'):'240',tag('hanging'):'240'})
        for rr in p.findall('w:r',ns):
            rp=rr.find('w:rPr',ns)
            if rp is None:rp=E.Element(tag('rPr'));rr.insert(0,rp)
            E.SubElement(rp,tag('b'),{tag('val'):'0'});E.SubElement(rp,tag('bCs'),{tag('val'):'0'})
    body.remove(sample_table);body.extend([main_carrier,final])
    changes={'word/document.xml':E.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True),
             'word/numbering.xml':E.tostring(numbering,xml_declaration=True,encoding='UTF-8',standalone=True)}
    for name in ['word/footer1.xml','word/footnotes.xml']:
        node=E.fromstring(z.read(name))
        for t in node.findall('.//w:t',ns):t.text=''
        changes[name]=E.tostring(node,xml_declaration=True,encoding='UTF-8',standalone=True)
    core=E.fromstring(z.read('docProps/core.xml'))
    for e in core:
        if E.QName(e).localname in ['creator','lastModifiedBy']:e.text='Nandana Raj; Harshit Gupta; Vaishnavi Ganesan'
        elif E.QName(e).localname=='title':e.text=TITLE
    changes['docProps/core.xml']=E.tostring(core,xml_declaration=True,encoding='UTF-8',standalone=True)
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as out:
        for entry in z.infolist():out.writestr(copy.copy(entry),changes.get(entry.filename,z.read(entry.filename)))
    with zipfile.ZipFile(output) as out:
        preserved=[n for n in z.namelist() if n not in changes]
        assert all(out.read(n)==z.read(n) for n in preserved)
        assert len(root.findall('.//w:sectPr',ns))==5
        assert 'template text' not in ''.join(root.itertext()).lower()
    assert Path(template).read_bytes()==source
    evidence=dict(template_sha256=hashlib.sha256(source).hexdigest(),output_sha256=hashlib.sha256(Path(output).read_bytes()).hexdigest(),
                  edited_parts=list(changes),preserved_parts=preserved,sections=5,authors=['Nandana Raj','Harshit Gupta','Vaishnavi Ganesan'])
    evidence['intentional_template_changes']=['Appended dedicated Roman section and per-section alphabetic subsection numbering definitions; original definitions retained','Caption numbering explicitly suppressed in favor of TABLE Roman labels','Reference bold explicitly disabled']
    evidence['reference_count']=len(citation_order)
    evidence['all_25_supplied_works_cited_in_body']=True
    evidence['pdf_reference_to_paper_reference']={str(i):citation_map['P'+str(i)] for i in range(1,26)}
    (ROOT/'results/study/conference_paper_build.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print(json.dumps(evidence,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--template',required=True)
    p.add_argument('--output',default=str(ROOT/'conference_paper.docx'))
    a=p.parse_args();build(a.template,a.output)
