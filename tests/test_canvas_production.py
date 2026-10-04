"""创作进度只读取真实节点、稳定关联与原文；不生成媒体。"""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class ProductionTests(unittest.TestCase):
    def run_js(self, body):
        result = subprocess.run(['node', '-e', "const assert=require('node:assert/strict');const p=require('./static/js/canvas-production.js');const c=require('./static/js/canvas-creation.js');" + body], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_segments_are_source_slices_and_notes_remain_free(self):
        self.run_js("""const script={id:'s',type:'smart-material',images:[{kind:'text',text:'第一句。第二句。'}]},segment={id:'p',type:'smart-material',images:[{kind:'text',text:'第二句。'}],creationDetails:'随意格式'}; const ns=[script,segment];p.update(segment,{role:'segment',order:1,sourceNodeId:'s',sourceStart:4,sourceEnd:8},ns);assert.equal(p.rows(ns)[0].number,1);assert.equal(segment.creationDetails,'随意格式');assert.equal(p.rows(ns)[0].sourceStatus,'current');script.images[0].text='第一句。新的句。';assert.equal(p.rows(ns)[0].sourceStatus,'changed');assert.throws(()=>p.update(segment,{sourceStart:0,sourceEnd:4},ns));""")

    def test_shared_reroll_and_fork_update_table_without_duplicate_media(self):
        self.run_js("""let seq=0;const id=()=>String(++seq);const a={id:'a',type:'smart-image-generator',images:[]};c.ensure(a,id);const b={...structuredClone(a),id:'b'};const s={id:'s',type:'smart-material',images:[{kind:'text',text:'原文'}]},t={...structuredClone(s),id:'t'};const ns=[a,b,s,t];p.update(s,{role:'segment',order:1,imageNodeIds:['a']},ns);p.update(t,{role:'segment',order:2,imageNodeIds:['b']},ns);assert.equal(p.rows(ns)[0].images[0].status,'not_generated');let task=c.begin(ns,a,id);task.runStatus='succeeded';c.publish(ns,task,[{kind:'image',url:'/one'}]);assert.equal(p.rows(ns)[1].images[0].media.url,'/one');task=c.begin(ns,b,id);task.runStatus='succeeded';c.publish(ns,task,[{kind:'image',url:'/two'}]);assert.equal(p.rows(ns)[0].images[0].media.url,'/one');assert.equal(p.rows(ns)[1].images[0].media.url,'/two');ns.splice(ns.indexOf(b),1);assert.equal(p.rows(ns)[1].images.length,0);""")

    def test_audio_placeholder_and_video_have_distinct_status_and_validate_links(self):
        self.run_js("""const s={id:'s',type:'smart-material',images:[{kind:'text',text:'原文'}]},a={id:'a',type:'smart-audio-generator',images:[],creationDetails:'声线设计，不是音频'},v={id:'v',type:'smart-video-generator',images:[{kind:'video',url:'/v.mp4'}]};const ns=[s,a,v];p.update(s,{role:'segment',order:100,audioNodeIds:['a'],videoNodeIds:['v']},ns);let r=p.rows(ns)[0];assert.equal(r.audio[0].status,'not_generated');assert.equal(r.videos[0].status,'ready');assert.throws(()=>p.update(s,{imageNodeIds:['a']},ns));assert.throws(()=>p.update(s,{audioNodeIds:['missing']},ns));assert.throws(()=>p.update(s,{order:1.5},ns));a.creationTasks=[{id:'run',runStatus:'failed',runError:'明确错误'}];assert.equal(p.rows(ns)[0].audio[0].status,'failed');""")

    def test_story_edges_are_authoritative_and_migrate_once(self):
        self.run_js("""const s={id:'s',type:'smart-material',images:[{kind:'text',text:'原文'}],production:{role:'segment',order:1,imageNodeIds:['a']}},a={id:'a',type:'smart-image-generator'},v={id:'v',type:'smart-video-generator'};const ns=[s,a,v],edges=[];assert.equal(p.migrateRelations(ns,edges),true);assert.equal(p.migrateRelations(ns,edges),false);assert.equal(s.production.imageNodeIds,undefined);assert.deepEqual(edges,[{from:'s',to:'a',kind:'story'}]);assert.equal(p.rows(ns,edges)[0].images[0].id,'a');edges.push({from:'s',to:'a',kind:'input'},{from:'a',to:'v',kind:'input'});edges.splice(0,1);assert.equal(p.rows(ns,edges)[0].images.length,0);p.update(s,{imageNodeIds:['a'],videoNodeIds:['v']},ns,edges);assert.equal(p.rows(ns,edges)[0].videos[0].id,'v');p.update(s,{imageNodeIds:[]},ns,edges);assert.equal(p.rows(ns,edges)[0].images.length,0);assert.ok(edges.some(c=>c.from==='s'&&c.to==='a'&&c.kind==='input'));assert.equal(s.production.imageNodeIds,undefined);""")

    def test_text_segment_registration_assigns_next_order_and_skips_ineligible_nodes(self):
        self.run_js("""const a={id:'a',type:'smart-material',images:[{kind:'text',text:'A'}]},b={id:'b',type:'smart-material',images:[{kind:'text',text:'B'}],production:{role:'segment',order:4}},script={id:'s',type:'smart-material',images:[{kind:'text',text:'Script'}],production:{role:'script'}},image={id:'i',type:'smart-material',images:[{kind:'image',url:'/i.png'}]};const ns=[a,b,script,image];assert.deepEqual(p.registerSegments(ns,['a','b','s','i'],[]),[a]);assert.equal(a.production.order,5);assert.equal(b.production.order,4);assert.deepEqual(p.registerSegments(ns,['a'],[]),[]);""")

    def test_progress_view_is_a_center_modal_without_panel_actions_or_auto_restore(self):
        source = (ROOT / "static/js/canvas-production.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/smart-canvas.css").read_text(encoding="utf-8")
        self.assertIn("setAttribute('aria-modal','true')", source)
        self.assertIn("button.addEventListener('click',()=>{const next=!el.classList.contains('open')", source)
        self.assertNotIn("data-pin", source)
        self.assertNotIn("data-register", source)
        self.assertNotIn("data-close", source)
        self.assertNotIn("localStorage", source)
        panel = css.split('/* 创作进度沿用价格对比', 1)[1].split('}', 1)[0]
        for layout in ('left:16px', 'right:16px', 'bottom:16px', 'height:min(70vh,680px)'):
            self.assertIn(layout, panel)
        self.assertIn(".canvas-production-panel.open", css)
        self.assertIn(".canvas-production-panel.open {opacity:1;visibility:visible;pointer-events:auto;transform:translateY(0);}", css)
        self.assertNotIn("place-items:center", css[css.index("/* 创作进度沿用价格对比"):])

class ModelClientTests(unittest.TestCase):
    run_js = ProductionTests.run_js
    def test_batch_keeps_successes_and_failed_request_is_not_retried(self):
        self.run_js("""const {create}=require('./static/js/canvas-model-client.js');let calls=0;const client=create({request:async()=>{if(++calls===2)throw Error('network');return {ok:true,json:async()=>({task_id:'t'+calls})}}});(async()=>{const settled=await client.submitMany('/api/mock',{},3);assert.equal(calls,3);assert.equal(settled.filter(s=>s.status==='fulfilled').length,2);assert.equal(settled.filter(s=>s.status==='rejected').length,1)})().catch(e=>{console.error(e);process.exitCode=1});""")

    def test_signal_and_error_are_passed_through_once(self):
        self.run_js("""const {create}=require('./static/js/canvas-model-client.js');const controller=new AbortController();let calls=0;const client=create({request:async(endpoint,options)=>{calls++;assert.equal(options.signal,controller.signal);assert.equal(JSON.parse(options.body).count,0);return {ok:false,status:400,text:async()=> '参数不合法'}}});(async()=>{await assert.rejects(()=>client.post('/api/mock',{count:0},{signal:controller.signal}),/参数不合法/);assert.equal(calls,1)})().catch(e=>{console.error(e);process.exitCode=1});""")
