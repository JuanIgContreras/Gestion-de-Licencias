document.addEventListener('DOMContentLoaded', function() {

    // --- LÓGICA GENERAL ---
    window.addEventListener('click', function(event) {
        if (event.target.classList.contains('modal')) {
            event.target.style.display = "none";
        }
    });

    // --- LÓGICA DEL DASHBOARD DE AGENTE ---
    const userMenuBtn = document.getElementById('userMenuBtn');
    const userMenuDropdown = document.getElementById('userMenuDropdown');
    const requestModal = document.getElementById('requestModal');
    const agentDetailModal = document.getElementById('agentSolicitudDetailModal');

    if (userMenuBtn && userMenuDropdown) {
        userMenuBtn.addEventListener('click', function(event) {
            event.stopPropagation();
            userMenuDropdown.classList.toggle('show');
        });

        window.addEventListener('click', function(event) {
            if (userMenuDropdown && !userMenuBtn.contains(event.target) && !userMenuDropdown.contains(event.target)) {
                userMenuDropdown.classList.remove('show');
            }
        });
    }
    
    if(requestModal) {
        const openModalBtn = document.getElementById('openModalBtn');
        const closeRequestModalBtn = document.getElementById('closeRequestModalBtn');

        if(openModalBtn) {
            openModalBtn.addEventListener('click', function(event) {
                event.preventDefault();
                requestModal.style.display = 'block';
                if(userMenuDropdown) userMenuDropdown.classList.remove('show');
            });
        }

        if(closeRequestModalBtn) {
            closeRequestModalBtn.addEventListener('click', function() {
                requestModal.style.display = 'none';
            });
        }
    }

    if (agentDetailModal) {
        const closeAgentDetailBtn = document.getElementById('closeAgentDetailModalBtn');
        if(closeAgentDetailBtn) {
            closeAgentDetailBtn.onclick = () => { agentDetailModal.style.display = 'none'; };
        }

        document.querySelectorAll('.view-agent-details-btn').forEach(button => {
            button.addEventListener('click', function() {
                const data = this.dataset;
                document.getElementById('agent-detail-tipo').textContent = data.tipo;
                document.getElementById('agent-detail-fecha').textContent = data.fecha;
                document.getElementById('agent-detail-dias').textContent = data.dias;
                document.getElementById('agent-detail-estado').textContent = data.estado;
                document.getElementById('agent-detail-comentario-agente').textContent = data.comentarioAgente;
                document.getElementById('agent-detail-comentario-admin').textContent = data.comentarioAdmin;
                agentDetailModal.style.display = 'block';
            });
        });
    }

    // --- LÓGICA DE PANELES DESPLEGABLES (ACORDEÓN - ADMIN) ---
    document.querySelectorAll('.section-header').forEach(header => {
        header.addEventListener('click', () => {
            const content = header.nextElementSibling;
            const toggleBtn = header.querySelector('.toggle-btn');
            
            document.querySelectorAll('.section-content').forEach(otherContent => {
                if (otherContent !== content && otherContent.style.display === 'block') {
                    otherContent.style.display = 'none';
                    otherContent.previousElementSibling.querySelector('.toggle-btn').classList.remove('is-open');
                }
            });

            const isVisible = content.style.display === 'block';
            content.style.display = isVisible ? 'none' : 'block';
            toggleBtn.classList.toggle('is-open', !isVisible);
        });
    });

    // --- LÓGICA PARA GESTIÓN DE AGENTES (ADMIN) ---
    const createAgentModal = document.getElementById('createAgentModal');
    if (createAgentModal) {
        document.getElementById('openCreateAgentModalBtn').onclick = () => { createAgentModal.style.display = 'block'; };
        document.getElementById('closeCreateAgentModalBtn').onclick = () => { createAgentModal.style.display = 'none'; };
    }

    const editAgentModal = document.getElementById('editAgentModal');
    if (editAgentModal) {
        document.getElementById('closeEditAgentModalBtn').onclick = () => { editAgentModal.style.display = 'none'; };

        document.querySelectorAll('.edit-agent-btn').forEach(button => {
            button.addEventListener('click', function() {
                const data = this.dataset;
                const form = document.getElementById('editAgentForm');
                
                form.action = `/admin/editar-agente/${data.id}`;
                document.getElementById('edit-nombre').value = data.nombre;
                document.getElementById('edit-usuario').value = data.usuario;
                document.getElementById('edit-enero').value = data.enero;
                document.getElementById('edit-julio').value = data.julio;
                document.getElementById('edit-comp').value = data.comp;
                document.getElementById('edit-nueva-clave').value = '';
                
                const isAdminCheckbox = document.getElementById('edit-es-admin');
                isAdminCheckbox.checked = (data.esAdmin === 'true');

                editAgentModal.style.display = 'block';
            });
        });
    }

    // Activar/Desactivar Agentes (SIN RECARGAR)
    document.querySelectorAll('.toggle-agent-btn').forEach(button => {
        button.addEventListener('click', function(event) {
            event.preventDefault();
            const agentId = this.dataset.id;
            const url = `/admin/toggle-agente/${agentId}`;
            const clickedButton = this;
            clickedButton.disabled = true;
            clickedButton.textContent = '...';

            fetch(url, { method: 'POST', headers: {'Content-Type': 'application/json'} })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    const agentRow = document.getElementById(`agente-row-${agentId}`);
                    if (agentRow) {
                        const statusBadge = agentRow.querySelector('.status-badge');
                        statusBadge.textContent = data.nuevo_estado_texto;
                        statusBadge.className = `status-badge ${data.nuevo_estado_clase}`;
                        clickedButton.textContent = data.nuevo_boton_texto;
                        clickedButton.className = `action-btn ${data.nuevo_boton_clase} toggle-agent-btn`;
                    }
                    showFlashMessage(data.message, 'success');
                } else {
                    showFlashMessage(data.error, 'danger');
                    clickedButton.textContent = clickedButton.classList.contains('deactivate') ? 'Desactivar' : 'Activar';
                }
            })
            .catch(error => {
                console.error('Fetch Error:', error);
                showFlashMessage('Ocurrió un error de red. Inténtalo de nuevo.', 'danger');
                clickedButton.textContent = clickedButton.classList.contains('deactivate') ? 'Desactivar' : 'Activar';
            })
            .finally(() => {
                clickedButton.disabled = false;
            });
        });
    });
    
    // --- LÓGICA PARA GESTIÓN DE SOLICITUDES (ADMIN) ---
    const tabContainer = document.querySelector('.tabs');
    if (tabContainer) {
        tabContainer.addEventListener('click', function(event) {
            if (event.target.classList.contains('tab-button')) {
                const tabId = event.target.dataset.tab;
                tabContainer.querySelectorAll('.tab-button').forEach(btn => btn.classList.remove('active'));
                event.target.classList.add('active');
                document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
                document.getElementById(tabId).classList.add('active');
            }
        });
    }

    const detailModal = document.getElementById('solicitudDetailModal');
    if (detailModal) {
        document.getElementById('closeDetailModalBtn').onclick = () => { detailModal.style.display = 'none'; };
        
        document.querySelectorAll('.view-details-btn').forEach(button => {
            button.addEventListener('click', function() {
                const data = this.dataset;
                document.getElementById('detail-agente').textContent = data.agente;
                document.getElementById('detail-tipo').textContent = data.tipo;
                document.getElementById('detail-fecha').textContent = data.fecha;
                document.getElementById('detail-dias').textContent = data.dias;
                document.getElementById('detail-comentario').textContent = data.comentario;
                
                document.getElementById('approve-form').action = `/aprobar_solicitud/${data.id}`;
                document.getElementById('reject-form').action = `/rechazar_solicitud/${data.id}`;
                
                document.getElementById('comentario_admin_text').value = '';
                detailModal.style.display = 'block';
            });
        });

        const adminCommentText = document.getElementById('comentario_admin_text');
        const approveForm = document.getElementById('approve-form');
        const rejectForm = document.getElementById('reject-form');

        if(adminCommentText && approveForm) {
            approveForm.addEventListener('submit', function() {
                this.querySelector('input[name="comentario_admin"]').value = adminCommentText.value;
            });
        }
        if(adminCommentText && rejectForm) {
            rejectForm.addEventListener('submit', function() {
                this.querySelector('input[name="comentario_admin"]').value = adminCommentText.value;
            });
        }
    }

    // --- LÓGICA PARA GESTIÓN DE NOVEDADES (ADMIN) ---
    const addNovedadModal = document.getElementById('addNovedadModal');
    if(addNovedadModal){
        document.getElementById('openNovedadModalBtn').onclick = () => { addNovedadModal.style.display = 'block'; };
        document.getElementById('closeAddModalBtn').onclick = () => { addNovedadModal.style.display = 'none'; };
    }

    const editNovedadModal = document.getElementById('editNovedadModal');
    if (editNovedadModal) {
        document.getElementById('closeEditModalBtn').onclick = () => { editNovedadModal.style.display = 'none'; };

        document.querySelectorAll('.edit-novedad-btn').forEach(button => {
            button.addEventListener('click', function() {
                const data = this.dataset;
                const form = document.getElementById('editNovedadForm');
                
                form.action = `/admin/editar-novedad/${data.id}`;
                document.getElementById('edit-titulo').value = data.titulo;
                document.getElementById('edit-mensaje').value = data.mensaje;
                
                editNovedadModal.style.display = 'block';
            });
        });
    }

    // --- CONFIRMACIONES (SWEETALERT2) ---
    document.body.addEventListener('submit', function(event) {
        if (event.target.classList.contains('rectify-form')) {
            event.preventDefault();
            const form = event.target;
            let confirmMessage = "¿Estás seguro de que quieres mover esta solicitud a 'Pendientes'?";
            if (form.closest('#aprobadas') !== null) {
                confirmMessage = "Los días descontados serán DEVUELTOS al agente. ¿Continuar?";
            }
            Swal.fire({
                title: 'Confirmar Acción', text: confirmMessage, icon: 'warning',
                showCancelButton: true, confirmButtonColor: '#3085d6', cancelButtonColor: '#d33',
                confirmButtonText: 'Sí, continuar', cancelButtonText: 'Cancelar'
            }).then((result) => { if (result.isConfirmed) { form.submit(); } });
        }
        
        if (event.target.classList.contains('delete-novedad-form')) {
            event.preventDefault();
            const form = event.target;
            Swal.fire({
                title: '¿Estás seguro?', text: "No podrás revertir esta acción.", icon: 'warning',
                showCancelButton: true, confirmButtonColor: '#d33', cancelButtonColor: '#3085d6',
                confirmButtonText: 'Sí, eliminar', cancelButtonText: 'Cancelar'
            }).then((result) => { if (result.isConfirmed) { form.submit(); } });
        }

        if (event.target.classList.contains('delete-agent-form')) {
            event.preventDefault();
            const form = event.target;
            const agentName = form.closest('tr').querySelector('td').textContent.trim();
            Swal.fire({
                title: '¡ACCIÓN IRREVERSIBLE!',
                html: `Estás a punto de eliminar permanentemente a <strong>${agentName}</strong> y todas sus solicitudes asociadas.<br><br>¿Estás completamente seguro?`,
                icon: 'error', showCancelButton: true, confirmButtonColor: '#d33',
                cancelButtonColor: '#3085d6', confirmButtonText: 'Sí, eliminar permanentemente',
                cancelButtonText: 'Cancelar'
            }).then((result) => { if (result.isConfirmed) { form.submit(); } });
        }
    });

    // --- FUNCIÓN AUXILIAR PARA MENSAJES DINÁMICOS ---
    function showFlashMessage(message, category) {
        const container = document.querySelector('.flash-container');
        if (container) {
            const alertDiv = document.createElement('div');
            alertDiv.className = `alert-${category} top-alert`;
            alertDiv.textContent = message;
            container.prepend(alertDiv);
            setTimeout(() => {
                alertDiv.style.opacity = '1';
                alertDiv.style.transform = 'translateY(0)';
            }, 10);
            setTimeout(() => {
                alertDiv.style.opacity = '0';
                alertDiv.style.transform = 'translateY(-20px)';
                setTimeout(() => alertDiv.remove(), 500);
            }, 5000);
        }
    }
});