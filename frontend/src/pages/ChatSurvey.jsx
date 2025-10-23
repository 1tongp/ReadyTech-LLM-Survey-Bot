import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Input, Button, Space, Tag, Typography, Divider } from 'antd'
import api from '../api'

export default function ChatSurvey(){
  const { token } = useParams()
  const navigate = useNavigate()

  const [meta, setMeta] = useState(null)
  const [respondentId, setRespondentId] = useState(null)
  const [answers, setAnswers] = useState([])
  const [idx, setIdx] = useState(0)
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const scrollerRef = useRef(null)

  // simple transcript: {role:'bot'|'user', html?:string, text?:string}
  const [chat, setChat] = useState([])

  useEffect(()=>{
    (async()=>{
      try{
        const {data} = await api.get(`/public/surveys/${token}`)
        setMeta(data)
        const r = await api.post('/public/respondents', { link_token: token })
        setRespondentId(r.data.respondent_id)
        // greet + first question
        setChat([
          {role:'bot', text:`Welcome! I’ll guide you through ${data.questions.length} question(s).`},
          {role:'bot', text:renderQuestionLine(data.questions[0], 1, data.questions.length)}
        ])
      }catch(e){
        setChat([{role:'bot', text:'⚠️ Invalid or inactive link. Please contact the survey owner.'}])
      }
    })()
  },[token])

  const questions = meta?.questions || []
  const currentQ = questions[idx]
  const readOnly = !!meta?.link_meta?.read_only

  const answeredMap = useMemo(()=>{
    const m = new Map()
    answers.forEach(a=>m.set(a.question_id, a))
    return m
  },[answers])

  const reloadAnswers = async()=>{
    if(!respondentId) return
    const {data} = await api.get(`/public/respondents/${respondentId}/answers`)
    setAnswers(data)
  }
  useEffect(()=>{ reloadAnswers() },[respondentId])

  useEffect(()=>{
    // when moving between questions, prefill draft and announce navigation
    if(!currentQ) return
    setDraft(answeredMap.get(currentQ.id)?.answer_text || '')
    botSay(`Now on Q${idx+1}/${questions.length}.`)
    botSay(renderQuestionLine(currentQ, idx+1, questions.length))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idx])

  useEffect(()=>{
    // autoscroll chat to bottom
    scrollerRef.current?.scrollTo({ top: scrollerRef.current.scrollHeight, behavior: 'smooth' })
  }, [chat, sending])

  function renderQuestionLine(q, n, total){
    let base = `Q${n}/${total}: ${q?.text || ''}`
    const g = q?.guideline?.content
    if (g) base += `\n(Guide: ${g})`
    return base
  }

  function botSay(text){
    setChat(prev=>[...prev, {role:'bot', text}])
  }
  function userSay(text){
    setChat(prev=>[...prev, {role:'user', text}])
  }

  const onSend = async()=>{
    if(!currentQ || !draft?.trim()) return
    setSending(true)
    const qid = currentQ.id
    const existing = answeredMap.get(qid)
    userSay(draft)

    try{
      let resp
      if (existing){
        resp = await api.put(`/public/answers/${existing.id}`, { answer_text: draft })
      }else{
        resp = await api.post('/public/answers', {
          respondent_id: respondentId, question_id: qid, answer_text: draft
        })
      }
      await reloadAnswers()

      // bot feedback + scoring in chat
      const data = resp.data || {}
      let fb = '✅ Saved.'
      if (typeof data.score === 'number'){
        fb += ` Score: ${data.score.toFixed(2)}`
      }
      if (data.low_quality){ fb += ' (⚠️ low quality detected)' }
      botSay(fb)
      if (data.rationale){
        botSay(`Reason: ${data.rationale}`)
      }
    }catch(e){
      botSay('❌ Failed to save. Please try again.')
    }finally{
      setSending(false)
    }
  }

  const onFlagToggle = async(makeFlag)=>{
    if(!currentQ) return
    const qid = currentQ.id
    const existing = answeredMap.get(qid)

    // ensure an answer row exists (create empty if needed)
    let answerId = existing?.id
    if (!answerId){
      const created = await api.post('/public/answers', {
        respondent_id: respondentId, question_id: qid, answer_text: draft || ''
      })
      await reloadAnswers()
      answerId = created.data?.id
    }

    await api.put(`/public/answers/${answerId}`, { flagged: makeFlag })
    await reloadAnswers()
    botSay(makeFlag ? '🚩 Question flagged.' : '✅ Unflagged.')
  }

  const goNext = ()=>{
    if (idx < questions.length - 1){
      botSay('➡️ Moving to next question.')
      setIdx(i=>i+1)
    } else {
      botSay('ℹ️ This is the last question.')
    }
  }
  const goPrev = ()=>{
    if (idx > 0){
      botSay('⬅️ Going back to previous question.')
      setIdx(i=>i-1)
    } else {
      botSay('ℹ️ This is the first question.')
    }
  }
  const onSubmitAll = async()=>{
    try{
      await api.post('/public/submit', { respondent_id: respondentId })
      botSay('🎉 Submitted. Thank you!')
    }catch{
      botSay('❌ Submit failed. Please try again.')
    }
  }

  if(!meta) return <Card loading title="Loading chat survey..." />

  const flagged = !!answeredMap.get(currentQ?.id || -1)?.flagged
  const score = answeredMap.get(currentQ?.id || -1)?.score
  const lowq = !!answeredMap.get(currentQ?.id || -1)?.low_quality
  
  return (
    <Card
      title={meta.survey.title}
      extra={<Button onClick={()=>navigate(`/take/${token}`)}>Form mode</Button>}
      bodyStyle={{padding:0}}
    >
      
      <div style={{padding:'12px 12px 0'}}>
        <Typography.Paragraph type="secondary" style={{marginBottom:8}}>
          Chat mode: {readOnly ? 'This survey is read-only.' : 'answer below, or use actions. I’ll reply with status and scoring.'}
        </Typography.Paragraph>
      </div>

      {/* Chat scroll area */}
      <div ref={scrollerRef} style={{height:'60vh', overflow:'auto', padding:'0 12px 12px'}}>
        {chat.map((m, i)=>(
          <div key={i} style={{
            display: 'flex',
            justifyContent: m.role==='bot' ? 'flex-start' : 'flex-end',
            marginTop: 8
          }}>
            <div style={{
              maxWidth: '80%',
              padding: '10px 12px',
              borderRadius: 12,
              background: m.role==='bot' ? '#f5f5f5' : '#1677ff',
              color: m.role==='bot' ? 'rgba(0,0,0,0.88)' : '#fff',
              whiteSpace: 'pre-wrap',
            }}>
              {m.text}
            </div>
          </div>
        ))}
      </div>

      {/* Composer + actions */}
      <div style={{borderTop:'1px solid #f0f0f0', padding:12}}>
        {currentQ && (
          <div style={{marginBottom:8}}>
            <Space size="small">
              {flagged ? <Tag color="red">Flagged</Tag> : null}
              {typeof score === 'number' ? <Tag>Score: {score.toFixed(2)}</Tag> : null}
              {lowq ? <Tag color="orange">Low Quality</Tag> : null}
            </Space>
          </div>
        )}
        <Space direction="vertical" style={{width:'100%'}}>
          <Input.TextArea
            rows={3}
            placeholder={currentQ ? `Your answer to Q${idx+1}...` : 'No question'}
            value={draft}
            onChange={e=>setDraft(e.target.value)}
            onPressEnter={(e)=>{ if(!e.shiftKey){ e.preventDefault(); onSend() }}}
            disabled={!currentQ}
          />
          <Space wrap>
            <Button onClick={goPrev} disabled={!currentQ || idx===0}>Previous</Button>
            <Button onClick={onSend} type="primary" loading={sending} disabled={!currentQ || !draft?.trim() || readOnly}>Save</Button>
            <Button onClick={goNext} disabled={!currentQ || idx===questions.length-1}>Next</Button>
            <Button onClick={()=>onFlagToggle(!flagged)} disabled={readOnly}>{flagged ? 'Unflag' : 'Flag'}</Button>
            <Button type="primary" onClick={onSubmitAll} disabled={readOnly || !answers.length}>Submit</Button>
          </Space>
        </Space>
      </div>
    </Card>
  )
}
