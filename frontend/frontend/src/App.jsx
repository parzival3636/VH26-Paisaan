import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { PipelineProvider } from './context/PipelineContext';
import Layout from './components/layout/Layout';
import Dashboard from './views/Dashboard';
import ControlCenter from './views/ControlCenter';
import BatchFiles from './views/BatchFiles';
import Benchmark from './views/Benchmark';

export default function App() {
  return (
    <PipelineProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="controls" element={<ControlCenter />} />
            <Route path="batches" element={<BatchFiles />} />
            <Route path="benchmark" element={<Benchmark />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </PipelineProvider>
  );
}
