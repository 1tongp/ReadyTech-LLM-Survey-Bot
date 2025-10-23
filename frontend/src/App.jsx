import { Layout, Menu } from 'antd'
import { Routes, Route, Link } from 'react-router-dom'

import Admin from './pages/Admin'
import ChatSurvey from './pages/ChatSurvey'
import TakeSurvey from './pages/TakeSurvey'

const { Header, Content, Footer } = Layout

export default function App(){
  const items = [
    { key: 'admin', label: <Link to="/admin">Admin</Link> },
    { key: 'take', label: <Link to="/take">Take Survey</Link> },
  ]
  return (
    <Layout style={{minHeight:'100vh'}}>
      <Header style={{display:'flex', alignItems:'center'}}>
        <div style={{color:'#fff', fontWeight:700, marginRight:24}}>Survey Bot</div>
        <Menu theme="dark" mode="horizontal" items={items}/>
      </Header>
      <Content style={{padding:24}}>
        <Routes>
          <Route path="/admin" element={<Admin/>} />
          <Route path="/take" element={<TakeSurvey/>} />
          <Route path="/take/:token" element={<TakeSurvey/>} />
          <Route path="/take/:token/chat" element={<ChatSurvey/>} />
          <Route path="*" element={<Admin/>} />
        </Routes>
      </Content>
      <Footer style={{textAlign:'center'}}>Built with Ant Design + FastAPI</Footer>
    </Layout>
  )
}
