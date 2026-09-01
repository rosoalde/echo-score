from abc import ABC, abstractmethod
from bbdd.response.user_response import UserResponse

class BASE_ROLE(ABC):
    
    def __init__(self, user: UserResponse):
        self.user = user
    
    ##################################
    #Funciones para la ejecución del proyecto "Nuevo Proyecto"
    ##################################
    @abstractmethod
    def proyecto_generar_termino(self):
        pass

    @abstractmethod
    def proyecto_ejecutar(self):
        pass
    
    ##################################
    #Funciones para la biblioteca de "Biblioteca"
    ##################################    
    @abstractmethod
    def biblioteca_consulta(self):
        pass

    @abstractmethod
    def biblioteca_descargar(self):
        pass

    @abstractmethod
    def biblioteca_eliminar(self):
        pass
    
    ##################################
    #Funciones para la biblioteca de "Dashboard"
    ##################################
    @abstractmethod
    def dashboard_select_proyecto(self):
        pass

    @abstractmethod
    def dashboard_filter_geo(self):
        pass

    @abstractmethod
    def dashboard_limpiar(self):
        pass

    @abstractmethod
    def dashboard_filter_topic(self):
        pass 

    @abstractmethod
    def dashboard_indicador_aceptacion(self):
        pass

    @abstractmethod
    def dashboard_prediccion(self):
        pass

    @abstractmethod
    def dashboard_generar_alertas(self):
        pass

    ##################################
    #Funciones para la actualización de datos de "Ajustes"
    ##################################
    @abstractmethod
    def ajustes_update_datos(self):
        pass

    @abstractmethod
    def ajustes_get_datos(self):
        pass