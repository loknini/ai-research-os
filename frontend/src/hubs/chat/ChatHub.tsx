import { BookOpen, Edit3, Trash2 } from 'lucide-react'
import { ChatSidebar } from './components/ChatSidebar'
import { ChatHeader } from './components/ChatHeader'
import { ChatMessageList } from './components/ChatMessageList'
import { ChatComposer } from './components/ChatComposer'
import { useChatController } from './hooks/useChatController'

export default function ChatHub() {
  const {
    ConfirmDialogComponent, conversations, currentConversation, isLoading,
    currentConversationId, setCurrentConversationId, input, setInput, pendingImages,
    isGenerating, genPhase, genElapsed, streamingContent, editingId, setEditingId,
    editTitle, setEditTitle, contextMenu, setContextMenu, copiedId, editingMessageId,
    setEditingMessageId, editBuffer, setEditBuffer, sidebarCollapsed, setSidebarCollapsed,
    drawerOpen, setDrawerOpen, activeMenuId, setActiveMenuId, sidebarWidth,
    isResizingSidebar, startResizeSidebar, resetSidebarWidth, contextInfo, ctxExpanded,
    setCtxExpanded, reasoningSteps, streamPanelOpen, setStreamPanelOpen,
    streamingRagSources, ragEnabled, ragSourceIds, setRagSourceIds, ragSourcesList,
    ragPickerOpen, setRagPickerOpen, scrollRef, inputRef, toggleRag,
    createNewConversation, deleteConversation, startEditTitle, saveTitle, sendMessage,
    handleCancel, startEditMessage, regenerate, editMessage, switchBranch,
    handleKeyDown, handleImageSelect, removeImage, copyMessage, branchTip, navigate
  } = useChatController()

  return (
    <div className="flex h-full bg-background relative">
      <ChatSidebar
        drawerOpen={drawerOpen}
        onDrawerClose={() => setDrawerOpen(false)}
        sidebarCollapsed={sidebarCollapsed}
        isResizing={isResizingSidebar}
        width={sidebarWidth}
        onResizeStart={startResizeSidebar}
        onResetWidth={resetSidebarWidth}
        conversations={conversations}
        currentConversationId={currentConversationId}
        isLoading={isLoading}
        editingId={editingId}
        editTitle={editTitle}
        activeMenuId={activeMenuId}
        onNewConversation={createNewConversation}
        onSelectConversation={setCurrentConversationId}
        onContextMenu={setContextMenu}
        onActiveMenuChange={setActiveMenuId}
        onEditTitleChange={setEditTitle}
        onSaveTitle={saveTitle}
        onStartEditTitle={startEditTitle}
        onDeleteConversation={deleteConversation}
        onCancelEdit={() => setEditingId(null)}
      />
      {/* 右键菜单兜底 */}
      {contextMenu && (
        <div
          id="chat-conv-context-menu"
          style={{ left: contextMenu.x, top: contextMenu.y }}
          className="fixed z-[100] min-w-[160px] rounded-lg border border-border/60 bg-popover text-popover-foreground shadow-lg overflow-hidden py-1"
        >
          <button
            onClick={() => {
              startEditTitle(contextMenu.conv)
              setContextMenu(null)
            }}
            className="w-full px-3 py-2 text-sm flex items-center gap-2 transition-colors text-left text-black dark:text-white hover:bg-accent focus-visible:bg-accent"
          >
            <Edit3 className="w-3.5 h-3.5 flex-shrink-0 text-black dark:text-white" />
            <span className="text-black dark:text-white">重命名</span>
          </button>
          <button
            onClick={() => {
              deleteConversation(contextMenu.conv.id)
              setContextMenu(null)
            }}
            className="w-full px-3 py-2 text-sm flex items-center gap-2 transition-colors text-left text-destructive hover:bg-destructive/10 focus-visible:bg-destructive/10"
          >
            <Trash2 className="w-3.5 h-3.5 flex-shrink-0" />
            <span>删除</span>
          </button>
        </div>
      )}

      {/* 右侧聊天区域 */}
      <div className="flex-1 flex flex-col min-w-0">
        <ChatHeader
          drawerOpen={drawerOpen}
          onToggleDrawer={() => setDrawerOpen((value) => !value)}
          sidebarCollapsed={sidebarCollapsed}
          onToggleSidebar={() => setSidebarCollapsed((value) => !value)}
          conversationTitle={currentConversation?.title}
          hasConversation={Boolean(currentConversation)}
          onNewConversation={() => {
            void createNewConversation().then(() => inputRef.current?.focus())
          }}
          branchTip={branchTip}
          contextInfo={contextInfo}
          contextExpanded={ctxExpanded}
          onToggleContext={() => setCtxExpanded((value) => !value)}
          ragEnabled={ragEnabled}
          onToggleRag={() => toggleRag(!ragEnabled)}
          ragPickerOpen={ragPickerOpen}
          onToggleRagPicker={() => setRagPickerOpen((value) => !value)}
          ragSources={ragSourcesList}
          selectedSourceIds={ragSourceIds}
          onSelectedSourceIdsChange={setRagSourceIds}
        />
        {/* 知识增强已开启但无已索引源时的提示条 */}
        {ragEnabled && ragSourcesList.length === 0 && (
          <div className="flex items-center gap-2 px-4 py-2 bg-amber-500/5 border-b border-amber-500/20 text-sm">
            <BookOpen className="w-4 h-4 text-amber-600 flex-shrink-0" />
            <span className="text-amber-700">
              当前空间还没有已索引的文档，知识增强将无法生效。
            </span>
            <button
              onClick={() => navigate('/settings#rag')}
              className="text-amber-600 hover:text-amber-700 underline underline-offset-2 font-medium ml-1"
            >
              前往设置建立索引 →
            </button>
          </div>
        )}

        <ChatMessageList
          scrollRef={scrollRef}
          conversation={currentConversation}
          onSuggestedPrompt={(prompt) => {
            void createNewConversation()
            setInput(prompt)
          }}
          editingMessageId={editingMessageId}
          editBuffer={editBuffer}
          onEditBufferChange={setEditBuffer}
          onCancelEdit={() => setEditingMessageId(null)}
          onEditMessage={editMessage}
          isGenerating={isGenerating}
          onSwitchBranch={switchBranch}
          onStartEditMessage={startEditMessage}
          onRegenerate={regenerate}
          copiedId={copiedId}
          onCopyMessage={copyMessage}
          reasoningSteps={reasoningSteps}
          streamPanelOpen={streamPanelOpen}
          onToggleStreamPanel={() => setStreamPanelOpen((value) => !value)}
          streamingContent={streamingContent}
          streamingRagSources={streamingRagSources}
          generationPhase={genPhase}
          generationElapsed={genElapsed}
        />
        <ChatComposer
          inputRef={inputRef}
          input={input}
          onInputChange={setInput}
          pendingImages={pendingImages}
          onRemoveImage={removeImage}
          onImageSelect={handleImageSelect}
          onKeyDown={handleKeyDown}
          hasConversation={Boolean(currentConversation)}
          isGenerating={isGenerating}
          onSend={sendMessage}
          onCancel={handleCancel}
        />
      </div>
      <ConfirmDialogComponent />
    </div>
  )
}
